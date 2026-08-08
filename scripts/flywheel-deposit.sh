#!/usr/bin/env bash
# flywheel-deposit: org-routed, main-push-only cache-WRITE deposit driver.
#
# The reusable spoke-deposit.yml lane runs this against a caller (adopter) repo's
# REAL Bazel action graph. It is the writer counterpart of the read-only
# cache-attachment lane in spoke-ci.yml: it exchanges the job's GitHub Actions
# OIDC identity for a gf-reapi-cell profile scoped to the caller's tenant and
# deposits the built action graph into the shared cache (CAS + action cache).
#
# THE SINGLE SAFETY INVARIANT (fail-closed, defence in depth):
#   upload=true (GF_BAZEL_REMOTE_UPLOAD=true / --remote_upload_local_results=true)
#   is UNREACHABLE unless the run is a trusted default-branch push. This mirrors
#   the server-side boundary the gf-reapi-cell exchange enforces
#   (policy.go GrantForGitHubClaims: ModeCacheWrite requires trustedDefaultBranchPush
#   provenance for refs/heads/<default>). A PR, a non-default push, a schedule, or
#   a workflow_dispatch NEVER sets upload=true here — the worst case is a
#   read-only build, exactly like the cache-attachment lane. The cell would in any
#   case only mint ModeCacheRead for those events, so a wrong upload flag could not
#   deposit anything; this driver refuses to even request it.
#
# Endpoint / identity authority is fleet-runtime env, NEVER baked here or in YAML
# (endpoint-free contract, TIN-2358):
#   BAZEL_REMOTE_CACHE                 shared Bazel cache (nix-setup exports it
#                                      from cluster DNS on the self-hosted runner)
#   GF_REAPI_TOKEN_EXCHANGE_ENDPOINT   hosted gf-reapi-token-exchange URL (fleet env)
#   GF_REAPI_CACHE_FRONTDOOR_ENDPOINT  enforce-cell front-door endpoint; supplied
#                                      into the ARC pod by the reviewed fleet
#                                      profile. Cache-WRITE is contingent on it —
#                                      absent, the lane degrades to cache-read.
#   GFW_OIDC_PROFILE_HELPER            absolute path to the fleet-projected
#                                      flywheel-github-oidc-profile, sha256-pinned.
#
# Caller-supplied deposit shape (from the reusable workflow inputs):
#   GFW_DEPOSIT_INSTANCE_NAME   expected REAPI instance the token must authorize
#                               (e.g. org-<owner> or consumer-<slug>). Required.
#   GFW_DEPOSIT_TENANT_NAME     expected tenant (default: GFW_DEPOSIT_INSTANCE_NAME).
#   GFW_DEPOSIT_TARGETS         space-separated REAL Bazel targets to deposit. Required.
#   GFW_DEPOSIT_BAZEL_COMMAND   build | test (default build).
#   GFW_DEPOSIT_DEFAULT_BRANCH  the trusted default branch (default main).
#   GF_OIDC_PROFILE_SHA256      lowercase sha256 pin for GFW_OIDC_PROFILE_HELPER.
#
# Runs outside GitHub Actions are explicit local diagnostics, never deposit
# evidence, and never write.

set -uo pipefail

EXPECTED_INSTANCE="${GFW_DEPOSIT_INSTANCE_NAME:?set GFW_DEPOSIT_INSTANCE_NAME to the expected REAPI instance (org-<owner> or consumer-<slug>)}"
EXPECTED_TENANT="${GFW_DEPOSIT_TENANT_NAME:-${EXPECTED_INSTANCE}}"
DEPOSIT_TARGETS="${GFW_DEPOSIT_TARGETS:?set GFW_DEPOSIT_TARGETS to the caller repo real Bazel targets}"
BAZEL_COMMAND="${GFW_DEPOSIT_BAZEL_COMMAND:-build}"
DEFAULT_BRANCH="${GFW_DEPOSIT_DEFAULT_BRANCH:-main}"
enforce_cell_endpoint="${GF_REAPI_CACHE_FRONTDOOR_ENDPOINT:-}"
profile_helper="${GFW_OIDC_PROFILE_HELPER:-}"
expected_profile_helper_sha256="${GF_OIDC_PROFILE_SHA256:-}"

note() { echo "::notice::flywheel-deposit: $*"; echo "flywheel-deposit: $*"; }
warn() { echo "::warning::flywheel-deposit: $*"; echo "flywheel-deposit: $*"; }
fail() { echo "ERROR: flywheel-deposit: $*" >&2; exit 1; }

case "${BAZEL_COMMAND}" in
build | test) ;;
*) fail "GFW_DEPOSIT_BAZEL_COMMAND must be build or test." ;;
esac

verify_profile_helper() {
  [[ "${profile_helper}" == /* ]] ||
    fail "GFW_OIDC_PROFILE_HELPER must be the absolute fleet-projected helper path."
  [[ -x "${profile_helper}" ]] ||
    fail "fleet-projected OIDC profile helper is absent or not executable."
  [[ "${expected_profile_helper_sha256}" =~ ^[0-9a-f]{64}$ ]] ||
    fail "GF_OIDC_PROFILE_SHA256 must be an exact lowercase SHA-256."
  local actual
  actual="$(sha256sum "${profile_helper}" | awk '{ print $1 }')"
  [[ "${actual}" == "${expected_profile_helper_sha256}" ]] ||
    fail "fleet-projected OIDC profile helper bytes do not match the reviewed SHA-256."
}

in_actions=false
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  in_actions=true
fi

# --- THE trusted-write gate (identical predicate to the server boundary) -----
# trustedDefaultBranchPush: event_name==push AND ref==refs/heads/<default>.
trusted_main_push=false
if [[ "${in_actions}" == "true" \
  && "${GITHUB_EVENT_NAME:-}" == "push" \
  && "${GITHUB_REF:-}" == "refs/heads/${DEFAULT_BRANCH}" ]]; then
  trusted_main_push=true
fi

# request_mode resolution. cache-write ONLY on a trusted default-branch push AND
# only when the enforce-cell front-door endpoint is present. Everything else is
# cache-read (upload=false). There is no code path to upload=true otherwise.
request_mode="cache-read"
if [[ "${trusted_main_push}" == "true" && -n "${enforce_cell_endpoint}" ]]; then
  request_mode="cache-write"
fi

case "${request_mode}" in
cache-read)
  profile_frontdoor_endpoint="${BAZEL_REMOTE_CACHE:-}"
  remote_upload=false
  ;;
cache-write)
  # Redundant with the gate above, but assert the invariant at the point of use:
  # cache-write is impossible without trusted default-branch push provenance.
  [[ "${trusted_main_push}" == "true" ]] ||
    fail "internal invariant violated: cache-write requested without trusted default-branch push."
  [[ -n "${enforce_cell_endpoint}" ]] ||
    fail "cache-write requires GF_REAPI_CACHE_FRONTDOOR_ENDPOINT from runner env; refusing to infer the enforce-cell endpoint."
  profile_frontdoor_endpoint="${enforce_cell_endpoint}"
  remote_upload=true
  ;;
esac

export GF_BAZEL_SUBSTRATE_MODE="${GF_BAZEL_SUBSTRATE_MODE:-shared-cache-backed}"
export GF_BAZEL_REMOTE_UPLOAD="${remote_upload}"
# CACHE-FIRST deposit: never an executor (TIN-1997 Option D). Remote execution is
# a separate authority and is intentionally not wired by the deposit lane.
export BAZEL_REMOTE_EXECUTOR=""
# Intended instance. The exchange profile, once produced, OVERRIDES this with the
# instance the token actually authorized — routing exactly what was granted.
export BAZEL_REMOTE_INSTANCE_NAME="${EXPECTED_INSTANCE}"

note "deposit intent: instance=${EXPECTED_INSTANCE} targets='${DEPOSIT_TARGETS}' command=${BAZEL_COMMAND} request=${request_mode} upload=${GF_BAZEL_REMOTE_UPLOAD} trusted_main_push=${trusted_main_push}"

if [[ "${in_actions}" == "true" ]]; then
  command -v nix >/dev/null 2>&1 || fail "nix is unavailable on the Actions runner."
  command -v bazelisk >/dev/null 2>&1 || command -v bazel >/dev/null 2>&1 || fail "bazelisk/bazel is unavailable on the Actions runner."
  [[ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]] || fail "ACTIONS_ID_TOKEN_REQUEST_URL is missing; OIDC exchange authority is unavailable."
  [[ -n "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]] || fail "ACTIONS_ID_TOKEN_REQUEST_TOKEN is missing; OIDC exchange authority is unavailable."
  [[ -n "${GF_REAPI_TOKEN_EXCHANGE_ENDPOINT:-}" ]] || fail "GF_REAPI_TOKEN_EXCHANGE_ENDPOINT is missing; token exchange authority is unavailable."
  [[ -n "${BAZEL_REMOTE_CACHE:-}" ]] || fail "BAZEL_REMOTE_CACHE is missing; cache authority is unavailable (nix-setup exports it from cluster DNS)."
  verify_profile_helper
else
  note "LOCAL DIAGNOSTIC ONLY: this run is outside GitHub Actions and is not deposit evidence; it will never write."
  if ! command -v nix >/dev/null 2>&1; then
    note "LOCAL DIAGNOSTIC ONLY: nix is unavailable; no deposit attempt was made."
    exit 0
  fi
  if ! command -v bazelisk >/dev/null 2>&1 && ! command -v bazel >/dev/null 2>&1; then
    note "LOCAL DIAGNOSTIC ONLY: bazelisk/bazel is unavailable; no deposit attempt was made."
    exit 0
  fi
fi

# --- Step 1 + 2: GitHub OIDC token exchange, source the minted profile --------
if [[ -n "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" && -n "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]]; then
  if [[ -n "${profile_helper}" && -n "${GF_REAPI_TOKEN_EXCHANGE_ENDPOINT:-}" ]]; then
    tokdir="$(mktemp -d)"
    profile="${tokdir}/gf-reapi-cell-profile.env"
    summary="${tokdir}/token-exchange-summary.json"
    if [[ "${in_actions}" == "true" ]]; then
      # Re-hash the exact absolute path immediately before executing it.
      verify_profile_helper
    fi
    if "${profile_helper}" \
      --request "${request_mode}" \
      --frontdoor-endpoint "${profile_frontdoor_endpoint}" \
      --profile-out "${profile}" \
      --summary-out "${summary}" >/dev/null 2>&1; then
      set -a
      # shellcheck disable=SC1090
      source "${profile}"
      set +a
      minted_instance="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("instance_name",""))' "${summary}" 2>/dev/null || true)"
      minted_tenant="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("tenant",""))' "${summary}" 2>/dev/null || true)"
      note "exchange authorized tenant=${minted_tenant:-<none>} instance=${minted_instance:-<none>}"
      if [[ "${minted_instance}" == "${EXPECTED_INSTANCE}" && "${minted_tenant}" == "${EXPECTED_TENANT}" ]]; then
        note "ACTIVATED: exchange authorized tenant=${EXPECTED_TENANT} instance=${EXPECTED_INSTANCE}."
      else
        if [[ "${in_actions}" == "true" ]]; then
          fail "exchange authorized tenant='${minted_tenant:-<none>}' instance='${minted_instance:-<none>}', expected tenant=${EXPECTED_TENANT} instance=${EXPECTED_INSTANCE}; refusing to deposit under the wrong tenant."
        fi
        warn "LOCAL DIAGNOSTIC ONLY: exchange authorized tenant='${minted_tenant:-<none>}' instance='${minted_instance:-<none>}', not the expected identity."
      fi
      if [[ "${in_actions}" == "true" ]]; then
        [[ -n "${BAZEL_REMOTE_CACHE:-}" ]] || fail "exchange profile did not provide cache authority."
        [[ -n "${BAZEL_CREDENTIAL_HELPER:-}" ]] || fail "exchange profile did not provide credential-helper cache authority."
        [[ -n "${GF_REAPI_CREDENTIAL_HELPER_TOKEN_FILE:-}" && -f "${GF_REAPI_CREDENTIAL_HELPER_TOKEN_FILE}" ]] || fail "exchange profile did not provide a readable credential-helper token file."
      fi
    else
      warn "token exchange call failed."
      if [[ "${in_actions}" == "true" ]]; then
        fail "token exchange call failed."
      fi
    fi
  else
    warn "fleet token-exchange front door unavailable (verified helper path absent or GF_REAPI_TOKEN_EXCHANGE_ENDPOINT unset)."
    if [[ "${in_actions}" == "true" ]]; then
      fail "fleet token-exchange front door unavailable."
    fi
  fi
else
  note "no GitHub Actions OIDC environment (local/dev run); skipping token exchange."
fi

# --- Step 3: cache-attached deposit build of the caller's REAL graph ---------
if [[ -z "${BAZEL_REMOTE_CACHE:-}" ]]; then
  warn "BAZEL_REMOTE_CACHE is unset after profile generation."
  if [[ "${in_actions}" == "true" ]]; then
    fail "BAZEL_REMOTE_CACHE is unset after profile generation; cache authority is unavailable."
  fi
  exit 0
fi

# Bazelisk dispatch: prefer host PATH, else the flake devShell.
if command -v bazelisk >/dev/null 2>&1; then
  bazel_cmd=(bazelisk)
elif command -v bazel >/dev/null 2>&1; then
  bazel_cmd=(bazel)
elif command -v nix >/dev/null 2>&1 && [[ -f flake.nix ]]; then
  bazel_cmd=(nix develop --command bazelisk)
else
  fail "bazelisk/bazel not on PATH and no flake.nix devShell available."
fi

remote_args=(
  --config=flywheel
  --remote_cache="${BAZEL_REMOTE_CACHE}"
  --remote_instance_name="${BAZEL_REMOTE_INSTANCE_NAME}"
  --remote_upload_local_results="${GF_BAZEL_REMOTE_UPLOAD}"
)
if [[ -n "${BAZEL_CREDENTIAL_HELPER:-}" ]]; then
  remote_args+=(--credential_helper="${BAZEL_CREDENTIAL_HELPER}")
fi
if [[ -n "${BAZEL_REMOTE_HEADER:-}" ]]; then
  remote_args+=(--remote_header="${BAZEL_REMOTE_HEADER}")
fi

note "cache-attached ${BAZEL_COMMAND} of '${DEPOSIT_TARGETS}' @ instance=${BAZEL_REMOTE_INSTANCE_NAME} (request=${request_mode}, upload=${GF_BAZEL_REMOTE_UPLOAD})"
# shellcheck disable=SC2086
if "${bazel_cmd[@]}" "${BAZEL_COMMAND}" "${remote_args[@]}" --verbose_failures ${DEPOSIT_TARGETS}; then
  note "deposit ${BAZEL_COMMAND} completed (instance=${BAZEL_REMOTE_INSTANCE_NAME}, request=${request_mode}, upload=${GF_BAZEL_REMOTE_UPLOAD})."
else
  rc=$?
  warn "deposit ${BAZEL_COMMAND} returned rc=${rc}; investigate cell auth + instance routing."
  exit "${rc}"
fi
