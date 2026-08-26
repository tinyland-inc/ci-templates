#!/usr/bin/env bash
# Negative/positive test harness for scripts/manifest-schema-validate.py.
#
# Two defects this pins down, both of which shipped fleet-wide:
#
#  1. The `repo-manifest-validate` composite hardcoded the v1 schema, so a
#     consumer that had migrated to the published `schema_version` 2 failed the
#     gate with `Additional properties are not allowed` plus `at
#     /schema_version: 1 was expected` — the gate blaming the manifest for a
#     branch the gate did not have. Routing is now total; these cases assert
#     each version reaches ITS schema and that anything unpublished fails
#     loudly with the value it saw rather than being routed to v1.
#
#  2. The dependency-free fallback validator implemented a JSON Schema subset
#     that did not include `not`, `anyOf`, or `contains` — which the v2 schema
#     uses to express every boundary rule (a static spoke must NOT claim
#     apply-plane authority; a layered role MUST contain its layer). Pointed at
#     the v2 schema, that subset returned 0 for manifests the authoritative
#     validator rejects. On the nix cluster runners the fallback exists FOR,
#     routing v2 correctly would have swapped a loud wrong answer for a silent
#     wrong answer. The subset now covers those keywords, and refuses outright
#     (exit 2) when a schema asserts with something it does not implement.
#
# Every case runs BOTH validator paths: once as the host finds it (authoritative
# `jsonschema` when installed) and once with `jsonschema` forced unimportable,
# so the stdlib fallback is exercised on this machine even where the package is
# present. A harness that only ever tests the path the developer happens to have
# is how defect 2 survived.
#
# Run: scripts/manifest-schema-validate-selftest.sh
# Wired into `just check` via `manifest-validate-selftest`.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${here}/.." && pwd)"
validator="${here}/manifest-schema-validate.py"
schemas="${root}/schemas"
fixtures="${root}/tests/fixtures"

for required in "${validator}" "${schemas}/tinyland-repo-manifest.schema.json" \
  "${schemas}/tinyland-repo-manifest.v2.schema.json" \
  "${fixtures}/repo-manifest-v2.json" "${root}/tinyland.repo.json"; do
  if [[ ! -e ${required} ]]; then
    echo "ERROR: missing ${required}" >&2
    exit 2
  fi
done

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

# Force `import jsonschema` to raise, so the stdlib fallback is the code under
# test. A stub module that raises ImportError is exactly what the validator's
# `except ImportError` sees on a runner without the package.
nojs="${work}/nojs"
mkdir -p "${nojs}"
printf 'raise ImportError("jsonschema hidden by manifest-schema-validate-selftest")\n' \
  >"${nojs}/jsonschema.py"

if python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import jsonschema' "${nojs}" \
  2>/dev/null; then
  echo "ERROR: the no-jsonschema shim did not hide the package; fallback cases would" >&2
  echo "       silently run the authoritative validator and prove nothing" >&2
  exit 2
fi

pass=0
fail=0

# run_case <expected_exit> <path-label> <description> -- <args to validator...>
run_case() {
  local expected="$1" label="$2" desc="$3"
  shift 4 # drop the literal `--`
  local out actual
  set +e
  if [[ ${label} == fallback ]]; then
    out="$(PYTHONPATH="${nojs}" python3 "${validator}" "$@" 2>&1)"
  else
    out="$(python3 "${validator}" "$@" 2>&1)"
  fi
  actual=$?
  set -e
  if [[ ${actual} -eq ${expected} ]]; then
    pass=$((pass + 1))
    printf 'ok   [%-13s exit %d] %s\n' "${label}" "${actual}" "${desc}"
  else
    fail=$((fail + 1))
    printf 'FAIL [%-13s exit %d, want %d] %s\n' "${label}" "${actual}" "${expected}" "${desc}"
    printf '       last: %s\n' "$(printf '%s\n' "${out}" | tail -1)"
  fi
}

# Assert a case's output mentions something, so an exit code alone cannot pass
# a check whose diagnostic has rotted into uselessness.
run_case_saying() {
  local expected="$1" label="$2" needle="$3" desc="$4"
  shift 5
  local out actual
  set +e
  if [[ ${label} == fallback ]]; then
    out="$(PYTHONPATH="${nojs}" python3 "${validator}" "$@" 2>&1)"
  else
    out="$(python3 "${validator}" "$@" 2>&1)"
  fi
  actual=$?
  set -e
  if [[ ${actual} -eq ${expected} ]] && printf '%s' "${out}" | grep -qF -- "${needle}"; then
    pass=$((pass + 1))
    printf 'ok   [%-13s exit %d] %s\n' "${label}" "${actual}" "${desc}"
  else
    fail=$((fail + 1))
    printf 'FAIL [%-13s exit %d, want %d saying %q] %s\n' \
      "${label}" "${actual}" "${expected}" "${needle}" "${desc}"
    printf '       last: %s\n' "$(printf '%s\n' "${out}" | tail -1)"
  fi
}

v1="${root}/tinyland.repo.json"
v2="${fixtures}/repo-manifest-v2.json"

# --- fixtures -------------------------------------------------------------

# Unpublished / mistyped / absent versions. Built from the REAL manifest so the
# only thing wrong with them is the version — a fixture that is invalid for two
# reasons cannot prove which one the gate caught.
jq '.schema_version = 7' "${v1}" >"${work}/version-7.json"
jq '.schema_version = "1.0.0"' "${v1}" >"${work}/version-semver.json"
jq 'del(.schema_version)' "${v1}" >"${work}/version-absent.json"
jq '.schema_version = true' "${v1}" >"${work}/version-true.json"

# Genuinely invalid v1: wrong type on a required field. (The old fixture here
# mutated schema_version to 2, which is now a PUBLISHED version — it would be
# asserting that a supported manifest is invalid.)
jq '.repo.name = 123' "${v1}" >"${work}/invalid-v1.json"

# Genuinely invalid v2, caught by a keyword the ORIGINAL subset enforced.
jq '.repo.name = 123' "${v2}" >"${work}/invalid-v2-type.json"

# Invalid v2 that ONLY a `contains` assertion catches: drop the layer the
# manifest's own primary_role requires. Nothing else about it is wrong, so a
# validator that ignores `contains` reports it valid. This is the exact shape
# the fallback used to wave through.
jq '.taxonomy.layers = ["org-wide-repo-contract","bazel-package-cache-rbe"]' "${v2}" \
  >"${work}/invalid-v2-contains.json"

# Schema directory missing the v2 schema: routing resolves, the file does not
# exist, so NOTHING validated the manifest. That is exit 4, never "valid".
partial="${work}/schemas-without-v2"
mkdir -p "${partial}"
cp "${schemas}/tinyland-repo-manifest.schema.json" "${partial}/"

# --- cases ----------------------------------------------------------------

for path in authoritative fallback; do
  run_case 0 "${path}" "v1 manifest routes to the v1 schema and validates" -- \
    --schemas-dir "${schemas}" "${v1}"
  run_case_saying 0 "${path}" "tinyland-repo-manifest.v2.schema.json" \
    "v2 manifest routes to the V2 schema and validates (the shipped defect)" -- \
    --schemas-dir "${schemas}" "${v2}"

  run_case_saying 3 "${path}" "schema_version 7" \
    "unpublished integer version exits 3 naming the value, not routed to v1" -- \
    --schemas-dir "${schemas}" "${work}/version-7.json"
  run_case_saying 3 "${path}" '"1.0.0"' \
    "the live semver-string dialect exits 3, not read as version 1" -- \
    --schemas-dir "${schemas}" "${work}/version-semver.json"
  run_case_saying 3 "${path}" "no schema_version" \
    "an absent schema_version exits 3; the gate does not assume 1" -- \
    --schemas-dir "${schemas}" "${work}/version-absent.json"
  run_case 3 "${path}" "schema_version true is not version 1 (bool subclasses int)" -- \
    --schemas-dir "${schemas}" "${work}/version-true.json"

  run_case 1 "${path}" "invalid v1 manifest fails closed" -- \
    --schemas-dir "${schemas}" "${work}/invalid-v1.json"
  run_case 1 "${path}" "invalid v2 manifest fails closed (type assertion)" -- \
    --schemas-dir "${schemas}" "${work}/invalid-v2-type.json"
  run_case 1 "${path}" "invalid v2 manifest fails closed (contains assertion only)" -- \
    --schemas-dir "${schemas}" "${work}/invalid-v2-contains.json"

  run_case_saying 4 "${path}" "was not validated against anything" \
    "a version routed to a schema absent from the checkout exits 4, never 0" -- \
    --schemas-dir "${partial}" "${v2}"

  # Explicit-schema form still works and is still load-bearing: it is how a
  # caller proves the two schemas are genuinely different documents.
  run_case 1 "${path}" "v2 manifest really is rejected BY the v1 schema" -- \
    "${schemas}/tinyland-repo-manifest.schema.json" "${v2}"
done

# The fallback must never report a verdict it cannot back. Every vendored
# schema has to be inside the subset it implements; if one grows a keyword the
# subset ignores, this fails here rather than draining the gate in production.
for schema in "${schemas}"/tinyland-repo-manifest*.schema.json; do
  if PYTHONPATH="${nojs}" python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import json
import importlib.util
spec = importlib.util.spec_from_file_location("msv", sys.argv[2])
msv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(msv)
msv.assert_fallback_covers(json.load(open(sys.argv[3], encoding="utf-8")))
' "${here}" "${validator}" "${schema}" 2>/dev/null; then
    pass=$((pass + 1))
    printf 'ok   [%-13s exit 0] fallback fully enforces %s\n' "coverage" "$(basename "${schema}")"
  else
    fail=$((fail + 1))
    printf 'FAIL [%-13s ] fallback cannot faithfully evaluate %s\n' "coverage" \
      "$(basename "${schema}")"
    PYTHONPATH="${nojs}" python3 -c '
import sys, json, importlib.util
spec = importlib.util.spec_from_file_location("msv", sys.argv[1])
msv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(msv)
try:
    msv.assert_fallback_covers(json.load(open(sys.argv[2], encoding="utf-8")))
except Exception as exc:
    print(f"       {exc}")
' "${validator}" "${schema}" || true
  fi
done

# And the guard itself must fire. A guard that has never been seen to reject is
# indistinguishable from one that is wired up wrong.
if PYTHONPATH="${nojs}" python3 -c '
import sys, importlib.util
spec = importlib.util.spec_from_file_location("msv", sys.argv[1])
msv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(msv)
try:
    msv.assert_fallback_covers({"type": "object", "dependentRequired": {"a": ["b"]}})
except msv.FallbackCoverageGap:
    raise SystemExit(0)
raise SystemExit(1)
' "${validator}"; then
  pass=$((pass + 1))
  printf 'ok   [%-13s exit 0] coverage guard rejects an unimplemented keyword\n' "coverage"
else
  fail=$((fail + 1))
  printf 'FAIL [%-13s ] coverage guard accepted a schema it cannot enforce\n' "coverage"
fi

printf '\n%d passed, %d failed\n' "${pass}" "${fail}"
[[ ${fail} -eq 0 ]]
