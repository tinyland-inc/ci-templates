#!/usr/bin/env bash
# Negative/positive test harness for scripts/manifest-schema-validate.py.
#
# Three defects this pins down, all of which shipped fleet-wide:
#
#  1. The `repo-manifest-validate` composite hardcoded the v1 schema, so a
#     consumer that had migrated to the published `schema_version` 2 failed the
#     gate with `Additional properties are not allowed` plus `at
#     /schema_version: 1 was expected` — the gate blaming the manifest for a
#     branch the gate did not have. Routing is now total; these cases assert
#     each version reaches ITS schema and that anything unpublished fails
#     loudly with the value it saw rather than being routed to v1.
#
#  2. A dependency-free fallback validator implemented a JSON Schema subset
#     that did not include `not`, `anyOf`, or `contains` — which the v2 schema
#     uses to express every boundary rule (a static spoke must NOT claim
#     apply-plane authority; a layered role MUST contain its layer). Pointed at
#     the v2 schema, that subset returned 0 for manifests the authoritative
#     validator rejects.
#
#     THE FALLBACK IS NOW DELETED (TIN-4132 / TIN-4192), so this file no longer
#     runs every case twice. The differential-lane machinery it used is gone
#     with it: two engines kept in step by a hand-written harness was the
#     hazard, not the fix. What replaces those cases is a REFUSAL contract —
#     with `jsonschema` hidden, the validator must exit 2 naming the dependency
#     and must NOT return a verdict of any kind. Those cases are the ones that
#     fail if a fallback is ever reintroduced, because a fallback would answer
#     0 or 1 where this file demands 2.
#
#  3. That same subset compared `const`/`enum` with Python `==`/`in`. `bool`
#     subclasses `int` in Python, so `True == 1`: a manifest declaring
#     `"schema_version": true` satisfied the v1 schema's `{"const": 1}`. Both
#     directions are still pinned below — `true` must be rejected, and `1.0`
#     must still be ACCEPTED, because JSON Schema compares numbers
#     mathematically. `_as_schema_version` applies the same rules to routing,
#     so `2.0` reaches the v2 schema instead of exiting 3 on a document that
#     schema accepts. These now assert the ROUTER against the authoritative
#     engine rather than one engine against another.
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

# Force `import jsonschema` to raise, so the REFUSAL path is exercised on this
# machine even where the package is present. A stub module that raises
# ImportError is exactly what the validator sees on a runner without it.
nojs="${work}/nojs"
mkdir -p "${nojs}"
printf 'raise ImportError("jsonschema hidden by manifest-schema-validate-selftest")\n' \
  >"${nojs}/jsonschema.py"

if python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import jsonschema' "${nojs}" \
  2>/dev/null; then
  echo "ERROR: the no-jsonschema shim did not hide the package; the refusal cases" >&2
  echo "       would silently run the real validator and prove nothing" >&2
  exit 2
fi

# There is one engine now, and it is not optional. On a host that cannot import
# `jsonschema` this harness cannot assert anything about validation, and saying
# "0 failed" there would be the same lie the fallback used to tell. Refuse,
# with the remedy, exactly as the gate itself does.
if ! python3 -c 'import jsonschema' >/dev/null 2>&1; then
  echo "ERROR: host python3 cannot import jsonschema." >&2
  echo "       The validator refuses to run without it (TIN-4132) and so does this" >&2
  echo "       selftest: a green run here would prove nothing about the engine." >&2
  echo "       Run inside \`nix develop\` (the ci devshell closure carries it)." >&2
  exit 2
fi

pass=0
fail=0

# run_case <expected_exit> <engine|refusal> <description> -- <args to validator...>
run_case() {
  local expected="$1" label="$2" desc="$3"
  shift 4 # drop the literal `--`
  local out actual
  set +e
  if [[ ${label} == refusal ]]; then
    out="$(PYTHONPATH="${nojs}" python3 "${validator}" "$@" 2>&1)"
  else
    out="$(python3 "${validator}" "$@" 2>&1)"
  fi
  actual=$?
  set -e
  if [[ ${actual} -eq ${expected} ]]; then
    pass=$((pass + 1))
    printf 'ok   [%-8s exit %d] %s\n' "${label}" "${actual}" "${desc}"
  else
    fail=$((fail + 1))
    printf 'FAIL [%-8s exit %d, want %d] %s\n' "${label}" "${actual}" "${expected}" "${desc}"
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
  if [[ ${label} == refusal ]]; then
    out="$(PYTHONPATH="${nojs}" python3 "${validator}" "$@" 2>&1)"
  else
    out="$(python3 "${validator}" "$@" 2>&1)"
  fi
  actual=$?
  set -e
  if [[ ${actual} -eq ${expected} ]] && printf '%s' "${out}" | grep -qF -- "${needle}"; then
    pass=$((pass + 1))
    printf 'ok   [%-8s exit %d] %s\n' "${label}" "${actual}" "${desc}"
  else
    fail=$((fail + 1))
    printf 'FAIL [%-8s exit %d, want %d saying %q] %s\n' \
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

# JSON equality, both directions (defect 3). These bypass the router with the
# explicit-schema form on purpose: routing rejects `true` before any schema is
# consulted, so only the direct form reaches the `const` comparison. The v1
# schema pins `"schema_version": {"const": 1}`.
jq '.schema_version = true' "${v1}" >"${work}/const-bool.json"   # true != 1 in JSON
jq '.schema_version = 1.0' "${v1}" >"${work}/const-float.json"   # 1.0 == 1 in JSON

# Routing must agree with the schema it routes to: 2.0 is an `integer` with a
# zero fractional part, which the v2 schema's `{"const": 2}` accepts.
jq '.schema_version = 2.0' "${v2}" >"${work}/version-2-float.json"

# ENGINE IDENTITY. `dependentRequired` is a real 2020-12 assertion that the
# deleted subset never implemented — it was in neither the enforced set nor the
# annotation set, so the subset refused outright rather than evaluating it.
# Demanding a VERDICT here (exit 1, from a violated dependency) is therefore a
# case only the authoritative engine can pass. If a fallback is ever restored
# and quietly preferred, this goes red instead of silently under-validating.
cat >"${work}/engine-probe.schema.json" <<'JSON'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "dependentRequired": { "schema_version": ["a_key_no_manifest_has"] }
}
JSON

# Genuinely invalid v1: wrong type on a required field.
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

# --- routing + validation, against the one engine --------------------------

run_case 0 engine "v1 manifest routes to the v1 schema and validates" -- \
  --schemas-dir "${schemas}" "${v1}"
run_case_saying 0 engine "tinyland-repo-manifest.v2.schema.json" \
  "v2 manifest routes to the V2 schema and validates (the shipped defect)" -- \
  --schemas-dir "${schemas}" "${v2}"

run_case_saying 3 engine "schema_version 7" \
  "unpublished integer version exits 3 naming the value, not routed to v1" -- \
  --schemas-dir "${schemas}" "${work}/version-7.json"
run_case_saying 3 engine '"1.0.0"' \
  "the live semver-string dialect exits 3, not read as version 1" -- \
  --schemas-dir "${schemas}" "${work}/version-semver.json"
run_case_saying 3 engine "no schema_version" \
  "an absent schema_version exits 3; the gate does not assume 1" -- \
  --schemas-dir "${schemas}" "${work}/version-absent.json"
run_case 3 engine "schema_version true is not version 1 (bool subclasses int)" -- \
  --schemas-dir "${schemas}" "${work}/version-true.json"
run_case_saying 0 engine "tinyland-repo-manifest.v2.schema.json" \
  "schema_version 2.0 routes to v2, as the v2 schema's own const 2 accepts it" -- \
  --schemas-dir "${schemas}" "${work}/version-2-float.json"

# JSON equality vs Python equality, pinned in both directions against the
# SCHEMA directly. Under `==`, the first of these passed: `True == 1`.
run_case 1 engine "a JSON boolean does NOT satisfy the v1 const 1 (True == 1 in Python)" -- \
  "${schemas}/tinyland-repo-manifest.schema.json" "${work}/const-bool.json"
run_case 0 engine "an integral float DOES satisfy the v1 const 1 (JSON numbers compare mathematically)" -- \
  "${schemas}/tinyland-repo-manifest.schema.json" "${work}/const-float.json"

run_case 1 engine "invalid v1 manifest fails closed" -- \
  --schemas-dir "${schemas}" "${work}/invalid-v1.json"
run_case 1 engine "invalid v2 manifest fails closed (type assertion)" -- \
  --schemas-dir "${schemas}" "${work}/invalid-v2-type.json"
run_case 1 engine "invalid v2 manifest fails closed (contains assertion only)" -- \
  --schemas-dir "${schemas}" "${work}/invalid-v2-contains.json"

run_case_saying 4 engine "was not validated against anything" \
  "a version routed to a schema absent from the checkout exits 4, never 0" -- \
  --schemas-dir "${partial}" "${v2}"

# Explicit-schema form still works and is still load-bearing: it is how a
# caller proves the two schemas are genuinely different documents.
run_case 1 engine "v2 manifest really is rejected BY the v1 schema" -- \
  "${schemas}/tinyland-repo-manifest.schema.json" "${v2}"

run_case_saying 1 engine "is a dependency of" \
  "control: a dependentRequired violation is REPORTED, which only the real engine can do" -- \
  "${work}/engine-probe.schema.json" "${v1}"

# --- the refusal contract (what replaced the fallback) ---------------------
#
# With `jsonschema` hidden, the validator must produce NO verdict. Every case
# here returned 0 or 1 before TIN-4132 — off the stdlib subset — so each one is
# a live guard against a fallback being reintroduced, not a tautology.

run_case_saying 2 refusal "jsonschema" \
  "a VALID v1 manifest yields no verdict without the engine (was exit 0 via the fallback)" -- \
  --schemas-dir "${schemas}" "${v1}"
run_case 2 refusal \
  "an INVALID v1 manifest yields 2 (refusal), not 1 — refusal is not a verdict" -- \
  --schemas-dir "${schemas}" "${work}/invalid-v1.json"
run_case 2 refusal \
  "the explicit-schema form refuses too; there is no un-gated entry point" -- \
  "${schemas}/tinyland-repo-manifest.schema.json" "${v1}"
run_case_saying 2 refusal "nix-setup" \
  "the refusal names the remedy, not just the missing import" -- \
  --schemas-dir "${schemas}" "${v2}"

# The engine check must come BEFORE the manifest is read, so a runner missing
# the dependency is told about the dependency rather than about a file. Same
# exit code, different message: assert the message.
run_case_saying 2 refusal "jsonschema" \
  "a missing manifest still reports the missing ENGINE, not the missing file" -- \
  --schemas-dir "${schemas}" "${work}/does-not-exist.json"

printf '\n%d passed, %d failed\n' "${pass}" "${fail}"
[[ ${fail} -eq 0 ]]
