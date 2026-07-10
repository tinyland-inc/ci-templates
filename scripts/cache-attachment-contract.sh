#!/usr/bin/env bash
# Classify the current Bazel cache/executor attachment without running Bazel.
#
# Generalized from MassageIthaca/scripts/cache-attachment-contract.sh (the merged,
# GF#889-proven shape) into a shared ci-templates entrypoint so any spoke can
# fail closed before a cache-backed Bazel invocation.
#
# Naming aligns with the TIN-2108 in-flight scripts (GF_BAZEL_SUBSTRATE_MODE;
# modes compatibility-local-only / shared-cache-backed / executor-backed) for
# easy convergence, while the fail-closed endpoint validation mirrors the proven
# MI logic verbatim.
#
# Classification:
#   BAZEL_REMOTE_EXECUTOR set  => executor-backed   (DEFINED + ENFORCED; never selected by any current repo)
#   else BAZEL_REMOTE_CACHE set => shared-cache-backed
#   else                        => compatibility-local-only
#
# The DECLARED mode is GF_BAZEL_SUBSTRATE_MODE. TIN-2109 makes this manifest-driven:
# the cache-backed lane reads tinyland.repo.json `enrollment.substrateMode` and
# exports it as GF_BAZEL_SUBSTRATE_MODE so the manifest is the AUTHORITATIVE
# expected mode. Declared-vs-actual is the effective_mode != expected_mode check.
#
# Fail-closed (exit 1) when:
#   - either endpoint contains a literal ${...} placeholder (unexpanded secret/var)
#   - either endpoint does not start with grpc://, grpcs://, http://, or https://
#   - localhost/127.0.0.1/::1 endpoint without GF_BAZEL_ALLOW_LOCALHOST_PROOF=true
#   - executor set without a cache endpoint
#   - executor != cache unless GF_BAZEL_ALLOW_SEPARATE_EXECUTOR_CACHE=true
#   - declared GF_BAZEL_SUBSTRATE_MODE disagreeing with endpoint presence
#   - declared GF_FLYWHEEL_PROFILE_STATE contradicting the selected substrate
#   - --strict with an empty BAZEL_REMOTE_CACHE
#   - (TIN-2109/TIN-2353) --strict on a hosted / non-cluster runner: a missing
#     substrate is a deterministic failure, never a silent degrade to a
#     GitHub-hosted build. Gated by GF_BAZEL_RUNNER_LABELS; accept
#     org-namespaced capability classes (`<org-pool>-nix|-nix-heavy|-nix-kvm|
#     -nix-gpu|-docker|-dind`) and reject ubuntu-*/windows-*/macos-*/bare
#     self-hosted labels. Override only with GF_BAZEL_ALLOW_HOSTED_RUNNER=true.
#   - (TIN-2109) declared/effective mode executor-backed without the FULL executor
#     contract: BAZEL_REMOTE_EXECUTOR + BAZEL_REMOTE_CACHE + a cluster runner class +
#     a proof-artifact image digest (GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST). This contract
#     is DEFINED + ENFORCED but selected by no current repo (cache-first / Option D).

set -euo pipefail

STRICT=false

usage() {
  cat >&2 <<'EOF'
Usage: scripts/cache-attachment-contract.sh [--strict]

Without --strict this reports whether the current shell is
compatibility-local-only, shared-cache-backed, or executor-backed. With --strict
it requires a real BAZEL_REMOTE_CACHE endpoint before cache-backed Bazel work
may run (the fail-closed gate for the cache-backed lane).

Environment:
  BAZEL_REMOTE_CACHE        Shared Bazel remote cache endpoint (grpc/grpcs/http/https).
  BAZEL_REMOTE_EXECUTOR     Optional remote executor endpoint. Classified as
                            executor-backed but NOT selected by the cache-first lane.
  GF_BAZEL_SUBSTRATE_MODE   Optional declared mode; must agree with endpoint presence.
  GF_FLYWHEEL_PROFILE_STATE Optional fleet enrollment state. Valid values:
                            unattached, shared-cache-backed, executor-backed,
                            local-proof. When set, it must agree with the
                            selected cache/executor environment.
  GF_BAZEL_ALLOW_LOCALHOST_PROOF
                            Set true to permit a localhost endpoint (explicit proof only).
  GF_BAZEL_ALLOW_SEPARATE_EXECUTOR_CACHE
                            Set true to permit executor != cache (default: GF REAPI cell
                            uses one endpoint for both).
  GF_BAZEL_RUNNER_LABELS    Optional comma/space-separated runner labels. When set under
                            --strict the gate REJECTS hosted (ubuntu-*/windows-*/macos-*),
                            bare self-hosted, and known repo-shaped fossils so a
                            missing substrate fails closed instead of degrading to a
                            GitHub-hosted build. Cluster classes are org-namespaced:
                            <org-pool>-nix, -nix-heavy, -nix-kvm, -nix-gpu,
                            -docker, or -dind (e.g. tinyland-nix,
                            great-falls-tool-bus-nix).
  GF_BAZEL_ALLOW_HOSTED_RUNNER
                            Set true to bypass the hosted/repo-label rejection (explicit
                            escape hatch only; the shared lane never enables it).
  GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST
                            Digest-pinned REAPI worker image. REQUIRED when the declared/
                            effective mode is executor-backed (proof-artifact wiring).
EOF
}

for arg in "$@"; do
  case "${arg}" in
  --strict)
    STRICT=true
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
  esac
done

remote_cache="${BAZEL_REMOTE_CACHE:-}"
remote_executor="${BAZEL_REMOTE_EXECUTOR:-}"
mode="${GF_BAZEL_SUBSTRATE_MODE:-}"
profile_state="${GF_FLYWHEEL_PROFILE_STATE:-}"

if [[ -n ${remote_executor} ]]; then
  expected_mode="executor-backed"
elif [[ -n ${remote_cache} ]]; then
  expected_mode="shared-cache-backed"
else
  expected_mode="compatibility-local-only"
fi

if [[ -z ${mode} ]]; then
  effective_mode="${expected_mode}"
else
  effective_mode="${mode}"
fi

context="developer-machine"
if [[ ${GITHUB_ACTIONS:-} == "true" ]]; then
  context="github-actions"
elif [[ -n ${CI:-} ]]; then
  context="ci"
fi

literal_cache=false
if [[ ${remote_cache} == *'${'* ]] || [[ ${remote_cache} == *'}'* ]]; then
  literal_cache=true
fi

literal_executor=false
if [[ ${remote_executor} == *'${'* ]] || [[ ${remote_executor} == *'}'* ]]; then
  literal_executor=true
fi

unsupported_cache=false
if [[ -n ${remote_cache} ]] && [[ ! ${remote_cache} =~ ^(grpc|grpcs|http|https):// ]]; then
  unsupported_cache=true
fi

unsupported_executor=false
if [[ -n ${remote_executor} ]] && [[ ! ${remote_executor} =~ ^(grpc|grpcs|http|https):// ]]; then
  unsupported_executor=true
fi

endpoint_is_localhost() {
  local endpoint="$1"
  local host
  host="${endpoint#*://}"
  host="${host%%/*}"
  host="${host%%:*}"
  host="${host#[}"
  host="${host%]}"
  case "${host}" in
  localhost | 127.0.0.1 | ::1 | 0.0.0.0) return 0 ;;
  *) return 1 ;;
  esac
}

# --- TIN-2109/TIN-2353: runner-class classification (reject hosted fallback) ---
# Cluster capability classes accepted for substrate-backed work are
# org-namespaced. This is a syntax check; the runner-pool grant itself lives in
# the operator/org overlay. Hosted, bare self-hosted, and known repo-label
# fossils remain silent-degrade vectors and fail closed in --strict.
runner_labels_raw="${GF_BAZEL_RUNNER_LABELS:-}"
allow_hosted_runner="${GF_BAZEL_ALLOW_HOSTED_RUNNER:-false}"
runner_class=""
runner_reject_reason=""
is_cluster_label() {
  if [[ "$1" =~ ^[a-z0-9][a-z0-9-]*-(nix|nix-heavy|nix-kvm|nix-gpu|docker|dind)$ ]]; then
    return 0
  fi
  return 1
}
is_known_repo_label_fossil() {
  case "$1" in
  dollhouse-farm-nix | chapel-nix | jesssullivan-nix-heavy | massageithaca-dind)
    return 0 ;;
  *) return 1 ;;
  esac
}
classify_runner() {
  # Sets runner_class to the first cluster-class label found. If none, sets
  # runner_reject_reason to the first disqualifying label (hosted / bare
  # self-hosted / known repo-label fossil), else leaves both empty (no labels
  # supplied).
  local raw="$1"
  raw="${raw//,/ }"
  local label
  for label in ${raw}; do
    if is_known_repo_label_fossil "${label}"; then
      runner_reject_reason="known repo-shaped runner label '${label}' (not an org capability class)"
      return 0
    fi
    if is_cluster_label "${label}"; then
      runner_class="${label}"
      return 0
    fi
  done
  for label in ${raw}; do
    case "${label}" in
    ubuntu-* | windows-* | macos-* | ubuntu | windows | macos)
      runner_reject_reason="hosted GitHub runner label '${label}'"
      return 0
      ;;
    self-hosted)
      runner_reject_reason="bare 'self-hosted' label (no capability class)"
      return 0
      ;;
    *-nix | *-nix-* | *-docker | *-dind)
      runner_reject_reason="runner label '${label}' does not match the org capability-class grammar"
      return 0
      ;;
    esac
  done
  if [[ -n ${raw// /} ]]; then
    runner_reject_reason="no org capability-class label in '${raw}'"
  fi
}
if [[ -n ${runner_labels_raw} ]]; then
  classify_runner "${runner_labels_raw}"
fi

allow_localhost="${GF_BAZEL_ALLOW_LOCALHOST_PROOF:-false}"
localhost_cache=false
if [[ -n ${remote_cache} ]] && endpoint_is_localhost "${remote_cache}"; then
  localhost_cache=true
fi
localhost_executor=false
if [[ -n ${remote_executor} ]] && endpoint_is_localhost "${remote_executor}"; then
  localhost_executor=true
fi

cat <<EOF
Bazel Cache Attachment
======================
Context:            ${context}
Bazel mode:         ${effective_mode}
Bazel remote cache: ${remote_cache:-unset}
Bazel executor:     ${remote_executor:-unset}
Expected mode:      ${expected_mode}
Flywheel profile:   ${profile_state:-unset}
Runner class:       ${runner_class:-${runner_labels_raw:+unclassified (${runner_labels_raw})}}
Strict:             ${STRICT}

Contract:
- cache-backed work gets its endpoint from BAZEL_REMOTE_CACHE
- executor-backed work gets BAZEL_REMOTE_EXECUTOR and uses BAZEL_REMOTE_CACHE
  as the CAS/action-cache authority; current GF lanes use the REAPI cell for both
  (executor-backed is classified here but NOT selected by the cache-first lane)
- the consumer .bazelrc keeps cache/executor endpoints out of checked-in defaults
- empty BAZEL_REMOTE_CACHE means compatibility-local-only; cache-backed
  entrypoints refuse it
EOF

if [[ ${effective_mode} != "${expected_mode}" ]]; then
  echo
  echo "ERROR: GF_BAZEL_SUBSTRATE_MODE=${effective_mode} disagrees with endpoint presence (expected ${expected_mode})."
  exit 1
fi

case "${profile_state}" in
"") ;;
unattached)
  if [[ -n ${remote_cache} || -n ${remote_executor} || ${effective_mode} != "compatibility-local-only" ]]; then
    echo
    echo "ERROR: GF_FLYWHEEL_PROFILE_STATE=unattached must not set cache/executor endpoints or a cache-backed mode."
    exit 1
  fi
  ;;
shared-cache-backed)
  if [[ ${effective_mode} != "shared-cache-backed" || -z ${remote_cache} || -n ${remote_executor} ]]; then
    echo
    echo "ERROR: GF_FLYWHEEL_PROFILE_STATE=shared-cache-backed requires GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed, BAZEL_REMOTE_CACHE, and no BAZEL_REMOTE_EXECUTOR."
    exit 1
  fi
  ;;
executor-backed)
  if [[ ${effective_mode} != "executor-backed" || -z ${remote_cache} || -z ${remote_executor} ]]; then
    echo
    echo "ERROR: GF_FLYWHEEL_PROFILE_STATE=executor-backed requires GF_BAZEL_SUBSTRATE_MODE=executor-backed plus cache and executor endpoints."
    exit 1
  fi
  ;;
local-proof)
  if [[ ${GF_BAZEL_LOCAL_PROOF:-} != "port-forward" ]]; then
    echo
    echo "ERROR: GF_FLYWHEEL_PROFILE_STATE=local-proof requires GF_BAZEL_LOCAL_PROOF=port-forward."
    exit 1
  fi
  case "${effective_mode}" in
  shared-cache-backed | executor-backed) ;;
  *)
    echo
    echo "ERROR: GF_FLYWHEEL_PROFILE_STATE=local-proof requires shared-cache-backed or executor-backed substrate mode."
    exit 1
    ;;
  esac
  ;;
*)
  echo
  echo "ERROR: GF_FLYWHEEL_PROFILE_STATE=${profile_state} is not recognized. Expected unattached, shared-cache-backed, executor-backed, or local-proof."
  exit 1
  ;;
esac

if [[ ${literal_cache} == "true" ]]; then
  echo
  echo "ERROR: BAZEL_REMOTE_CACHE is a literal shell placeholder, not a real endpoint."
  exit 1
fi

if [[ ${literal_executor} == "true" ]]; then
  echo
  echo "ERROR: BAZEL_REMOTE_EXECUTOR is a literal shell placeholder, not a real endpoint."
  exit 1
fi

if [[ ${unsupported_cache} == "true" ]]; then
  echo
  echo "ERROR: BAZEL_REMOTE_CACHE must start with grpc://, grpcs://, http://, or https://."
  exit 1
fi

if [[ ${unsupported_executor} == "true" ]]; then
  echo
  echo "ERROR: BAZEL_REMOTE_EXECUTOR must start with grpc://, grpcs://, http://, or https://."
  exit 1
fi

if [[ ${localhost_cache} == "true" && ${allow_localhost} != "true" ]]; then
  echo
  echo "ERROR: BAZEL_REMOTE_CACHE points at localhost. Set GF_BAZEL_ALLOW_LOCALHOST_PROOF=true only with explicit proof; the shared lane expects the cluster cache endpoint."
  exit 1
fi

if [[ ${localhost_executor} == "true" && ${allow_localhost} != "true" ]]; then
  echo
  echo "ERROR: BAZEL_REMOTE_EXECUTOR points at localhost. Set GF_BAZEL_ALLOW_LOCALHOST_PROOF=true only with explicit proof."
  exit 1
fi

if [[ -n ${remote_executor} && -z ${remote_cache} ]]; then
  echo
  echo "ERROR: executor-backed mode requires BAZEL_REMOTE_CACHE."
  exit 1
fi

if [[ -n ${remote_executor} && -n ${remote_cache} &&
  ${remote_cache} != "${remote_executor}" &&
  ${GF_BAZEL_ALLOW_SEPARATE_EXECUTOR_CACHE:-false} != "true" ]]; then
  echo
  echo "ERROR: executor-backed mode requires BAZEL_REMOTE_CACHE to match BAZEL_REMOTE_EXECUTOR for the GloriousFlywheel REAPI cell."
  exit 1
fi

# TIN-2109/TIN-2353: reject hosted / non-cluster runner fallback under --strict. A
# missing substrate must be a deterministic failure, never a silent degrade to a
# GitHub-hosted build. Only enforced when runner labels are supplied AND --strict
# is on, so non-cache-backed callers stay unaffected.
if [[ ${STRICT} == "true" && -n ${runner_labels_raw} && -z ${runner_class} &&
  ${allow_hosted_runner} != "true" ]]; then
  echo
  echo "ERROR: strict cache-backed lane refuses to run on ${runner_reject_reason:-a non-cluster runner}. The substrate must attach on an org-namespaced capability-class runner (<org-pool>-nix|-nix-heavy|-nix-kvm|-nix-gpu|-docker|-dind). Hosted/non-cluster fallback is rejected; set GF_BAZEL_ALLOW_HOSTED_RUNNER=true only with explicit non-shared-lane justification."
  exit 1
fi

# TIN-2109: executor-backed contract. When the declared/effective mode is
# executor-backed, the FULL contract is required and any missing piece fails
# closed. This is DEFINED + ENFORCED here but selected by NO current repo
# (cache-first / TIN-1997 Option D); kit/bridge declare shared-cache-backed.
if [[ ${effective_mode} == "executor-backed" || -n ${remote_executor} ]]; then
  if [[ -z ${remote_executor} ]]; then
    echo
    echo "ERROR: declared substrateMode=executor-backed requires BAZEL_REMOTE_EXECUTOR (the REAPI executor endpoint)."
    exit 1
  fi
  if [[ -z ${remote_cache} ]]; then
    echo
    echo "ERROR: executor-backed mode requires BAZEL_REMOTE_CACHE (the CAS/action-cache authority)."
    exit 1
  fi
  if [[ -n ${runner_labels_raw} && -z ${runner_class} && ${allow_hosted_runner} != "true" ]]; then
    echo
    echo "ERROR: executor-backed mode requires a cluster runner class for GloriousFlywheel platform identity (gf.platform=gloriousflywheel-rbe-linux-x86_64); got ${runner_reject_reason:-no capability-class label}."
    exit 1
  fi
  if [[ -z ${GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST:-} ]]; then
    echo
    echo "ERROR: executor-backed mode requires GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST (the digest-pinned REAPI worker image for proof-artifact wiring). The flywheel-reapi-proof authority must publish evidence with remote_processes > 0 and a worker_image_digest before a target class is proved."
    exit 1
  fi
fi

if [[ ${STRICT} == "true" && -z ${remote_cache} ]]; then
  echo
  echo "ERROR: strict mode requires BAZEL_REMOTE_CACHE to be set."
  exit 1
fi

echo
echo "Status: ${expected_mode}"
