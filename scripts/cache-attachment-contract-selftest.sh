#!/usr/bin/env bash
# TIN-2109 negative-test harness for scripts/cache-attachment-contract.sh.
#
# Proves the fail-closed paths actually fail closed and the happy paths pass,
# WITHOUT running Bazel or touching the network. Each case asserts an exact exit
# code (0 = attach OK, 1 = fail closed) so a regression flips a check.
#
# Run: scripts/cache-attachment-contract-selftest.sh
# Wired into `just check` via `cache-contract-selftest`.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
contract="${here}/cache-attachment-contract.sh"

if [[ ! -x ${contract} ]]; then
  echo "ERROR: contract script not found/executable at ${contract}" >&2
  exit 2
fi

pass=0
fail=0

# run_case <expected_exit> <description> [VAR=val ...]
run_case() {
  local expected="$1"
  local desc="$2"
  shift 2
  local out actual
  set +e
  out="$(env -i PATH="$PATH" "$@" bash "${contract}" --strict 2>&1)"
  actual=$?
  set -e
  if [[ ${actual} -eq ${expected} ]]; then
    pass=$((pass + 1))
    printf 'ok   [exit %d] %s\n' "${actual}" "${desc}"
  else
    fail=$((fail + 1))
    printf 'FAIL [exit %d, want %d] %s\n' "${actual}" "${expected}" "${desc}"
    printf '       last: %s\n' "$(printf '%s\n' "${out}" | tail -1)"
  fi
}

CACHE="grpcs://gf-reapi-cell.internal:443"

echo "== happy paths (exit 0) =="
# Current kit/bridge shape: cache attaches, declared shared-cache-backed, cluster runner.
run_case 0 "shared-cache attaches on cluster runner, declared shared-cache-backed" \
  BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed GF_BAZEL_RUNNER_LABELS=tinyland-nix
# Back-compat: no runner labels supplied (pre-TIN-2109 callers).
run_case 0 "shared-cache attaches, no runner labels supplied (back-compat)" \
  BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed
# Full executor contract present => executor-backed classification passes.
run_case 0 "executor-backed full contract present" \
  BAZEL_REMOTE_EXECUTOR="${CACHE}" BAZEL_REMOTE_CACHE="${CACHE}" \
  GF_BAZEL_RUNNER_LABELS=tinyland-nix GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST=sha256:deadbeef \
  GF_BAZEL_SUBSTRATE_MODE=executor-backed

echo "== declared-vs-actual mismatch (exit 1) =="
run_case 1 "declared shared-cache-backed but no cache attaches" \
  GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed
run_case 1 "declared compatibility-local-only but a cache IS attached" \
  BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_SUBSTRATE_MODE=compatibility-local-only GF_BAZEL_RUNNER_LABELS=tinyland-nix

echo "== hosted / repo-label fallback rejection (exit 1) =="
run_case 1 "hosted ubuntu-latest runner" \
  BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed GF_BAZEL_RUNNER_LABELS=ubuntu-latest
run_case 1 "repo-shaped <name>-nix runner label" \
  BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed GF_BAZEL_RUNNER_LABELS=jesssullivan-nix-heavy
run_case 1 "bare self-hosted label (no capability class)" \
  BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed GF_BAZEL_RUNNER_LABELS=self-hosted

echo "== executor-backed without required set (exit 1) =="
run_case 1 "executor endpoint set but no cache" \
  BAZEL_REMOTE_EXECUTOR="${CACHE}" GF_BAZEL_RUNNER_LABELS=tinyland-nix
run_case 1 "executor+cache+cluster but no REAPI proof image digest" \
  BAZEL_REMOTE_EXECUTOR="${CACHE}" BAZEL_REMOTE_CACHE="${CACHE}" GF_BAZEL_RUNNER_LABELS=tinyland-nix
run_case 1 "executor full set but hosted runner (no platform identity)" \
  BAZEL_REMOTE_EXECUTOR="${CACHE}" BAZEL_REMOTE_CACHE="${CACHE}" \
  GF_BAZEL_RUNNER_LABELS=ubuntu-latest GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST=sha256:deadbeef

echo "== pre-existing endpoint fail-closed (exit 1) =="
run_case 1 "unexpanded \${...} placeholder cache endpoint" \
  BAZEL_REMOTE_CACHE='${BAZEL_REMOTE_CACHE}' GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed
run_case 1 "non-grpc/http cache endpoint scheme" \
  BAZEL_REMOTE_CACHE='ftp://cache' GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed
run_case 1 "localhost cache without GF_BAZEL_ALLOW_LOCALHOST_PROOF" \
  BAZEL_REMOTE_CACHE='grpc://localhost:9092' GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed
run_case 1 "strict with empty BAZEL_REMOTE_CACHE (compat declared compat)" \
  GF_BAZEL_SUBSTRATE_MODE=compatibility-local-only

echo
echo "cache-attachment-contract self-test: ${pass} passed, ${fail} failed"
if [[ ${fail} -ne 0 ]]; then
  exit 1
fi
