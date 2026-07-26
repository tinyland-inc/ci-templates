#!/usr/bin/env bash

set -euo pipefail

# Seal command lookup before the first external command. The consumer checkout,
# caller PATH, Python startup hooks, and Bazelisk override variables never
# participate in bootstrap tool selection.
readonly SAFE_SYSTEM_PATH="/usr/bin:/bin:/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin"
export PATH="$SAFE_SYSTEM_PATH"
unset BASH_ENV ENV CDPATH GLOBIGNORE PYTHONHOME PYTHONPATH PYTHONSTARTUP \
  PYTHONUSERBASE BAZELISK_BASE_URL BAZELISK_FORMAT_URL USE_BAZEL_VERSION \
  BAZEL_REAL ROUTINE_RBE_GIT
hash -r

die() {
  printf '::error::%s\n' "$*" >&2
  exit 1
}

require_value() {
  local name="$1"
  [[ -n ${!name:-} ]] || die "$name is required for guarded routine RBE"
}

validate_sha256() {
  [[ $1 =~ ^[0-9a-f]{64}$ ]] || die "invalid SHA-256 pin: $1"
}

resolve_trusted_tool() {
  local name="$1"
  local candidate

  for candidate in \
    "/usr/bin/$name" \
    "/bin/$name" \
    "/run/current-system/sw/bin/$name" \
    "/nix/var/nix/profiles/default/bin/$name"; do
    if [[ -f $candidate && -x $candidate ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  die "trusted $name is required at a fixed system path"
}

sha256_path() {
  local digest remainder
  read -r digest remainder < <("${SHA256_BIN}" "$1")
  printf '%s\n' "$digest"
}

verify_sha256() {
  local path="$1"
  local expected="$2"
  local description="$3"
  local actual

  validate_sha256 "$expected"
  actual="$(sha256_path "$path")"
  [[ $actual == "$expected" ]] ||
    die "$description SHA-256 mismatch: expected $expected, got $actual"
}

download_exact() {
  local url="$1"
  local destination="$2"

  [[ $url == https://github.com/* ]] || die "tool download must use an exact GitHub HTTPS URL"
  [[ $url != *'/latest/'* ]] || die "floating latest download URLs are forbidden"
  "${CURL_BIN}" --disable --proto '=https' --tlsv1.2 --fail --silent --show-error \
    --location --output "$destination" -- "$url"
}

append_if_set() {
  local name="$1"
  if [[ -n ${!name:-} ]]; then
    CLEAN_ENV+=("$name=${!name}")
  fi
}

[[ ${ROUTINE_RBE_ENABLED:-false} == true ]] ||
  die "routine RBE is default-off; set the dedicated routine_rbe input to true"
[[ ${ROUTINE_RBE_CACHE_BACKED:-false} == true ]] ||
  die "routine RBE requires the separately opted cache_backed=true substrate path"
[[ -z ${ROUTINE_RBE_TRUSTED_ROOT:-} ]] ||
  die "local trusted-root substitution is forbidden"
[[ -z ${TIN2851_SELFTEST:-} && -z ${TIN2851_SELFTEST_REMOTE:-} ]] ||
  die "selftest trust overrides are forbidden in a routine-RBE invocation"
UNAME_BIN="$(resolve_trusted_tool uname)"
[[ $("$UNAME_BIN" -s) == Linux && $("$UNAME_BIN" -m) == x86_64 ]] ||
  die "routine RBE is admitted only on the proved Linux x86_64 worker platform"

for name in \
  GITHUB_WORKSPACE RUNNER_TEMP ROUTINE_RBE_ACTION_REF ROUTINE_RBE_WORKFLOW_REF \
  ROUTINE_RBE_ACTION_REPOSITORY ROUTINE_RBE_WORKFLOW_SHA \
  ROUTINE_RBE_WORKFLOW_REPOSITORY ROUTINE_RBE_WORKFLOW_FILE_PATH \
  ROUTINE_RBE_JOB_WORKFLOW_REF ROUTINE_RBE_JOB_WORKFLOW_SHA \
  ROUTINE_RBE_JOB_WORKFLOW_REPOSITORY ROUTINE_RBE_JOB_WORKFLOW_FILE_PATH \
  ROUTINE_RBE_LANES_PATH ROUTINE_RBE_LANE ROUTINE_RBE_RUNNER_LABELS \
  ROUTINE_RBE_TARGET_CLASS ROUTINE_RBE_TARGET ROUTINE_RBE_BAZEL_COMMAND \
  ROUTINE_RBE_RUN_SHA256 ROUTINE_RBE_GUARD_SHA256 ROUTINE_RBE_TOOLCHAIN_SHA256 \
  ROUTINE_RBE_PYTHON_URL ROUTINE_RBE_PYTHON_SHA256 BAZEL_REMOTE_CACHE \
  BAZEL_REMOTE_EXECUTOR; do
  require_value "$name"
done

[[ ${ROUTINE_RBE_ACTION_REPOSITORY:-} == tinyland-inc/ci-templates ]] ||
  die "routine-rbe action must be loaded from tinyland-inc/ci-templates"
[[ ${GF_BAZEL_SUBSTRATE_MODE:-} == executor-backed ]] ||
  die "GF_BAZEL_SUBSTRATE_MODE must be executor-backed for the guarded path"
[[ ${GF_FLYWHEEL_PROFILE_STATE:-} == executor-backed ]] ||
  die "GF_FLYWHEEL_PROFILE_STATE must be executor-backed for the guarded path"
[[ ${GF_BAZEL_REMOTE_UPLOAD:-false} == false ]] ||
  die "routine RBE is proof-only and forbids remote cache publication"
[[ ${BAZEL_REMOTE_CACHE} == "${BAZEL_REMOTE_EXECUTOR}" ]] ||
  die "routine RBE requires one unified REAPI cache/executor authority"
for endpoint_name in BAZEL_REMOTE_CACHE BAZEL_REMOTE_EXECUTOR; do
  endpoint="${!endpoint_name}"
  [[ $endpoint =~ ^grpcs?:// ]] || die "$endpoint_name must use grpc:// or grpcs://"
  [[ $endpoint != *'${'* && $endpoint != *'}'* ]] ||
    die "$endpoint_name contains an unexpanded placeholder"
done

runner_class=""
for label in ${ROUTINE_RBE_RUNNER_LABELS//,/ }; do
  if [[ $label =~ ^[a-z0-9][a-z0-9-]*-(nix|nix-heavy|nix-kvm|nix-gpu|docker|dind)$ ]]; then
    runner_class="$label"
    break
  fi
done
[[ -n $runner_class ]] ||
  die "routine RBE requires an org capability-class ARC runner; ARC placement alone is not proof"

workspace="$(cd "$GITHUB_WORKSPACE" && pwd -P)"
script_dir="${BASH_SOURCE[0]%/*}"
repo_root="$(cd "$script_dir/.." && pwd -P)"
[[ $repo_root != "$workspace" ]] ||
  die "consumer checkout cannot be used as the routine-RBE action source root"

CURL_BIN="$(resolve_trusted_tool curl)"
TAR_BIN="$(resolve_trusted_tool tar)"
GIT_BIN="$(resolve_trusted_tool git)"
SHA256_BIN="$(resolve_trusted_tool sha256sum)"
MKTEMP_BIN="$(resolve_trusted_tool mktemp)"
MKDIR_BIN="$(resolve_trusted_tool mkdir)"
RM_BIN="$(resolve_trusted_tool rm)"
CHMOD_BIN="$(resolve_trusted_tool chmod)"
FIND_BIN="$(resolve_trusted_tool find)"
TEE_BIN="$(resolve_trusted_tool tee)"
INSTALL_BIN="$(resolve_trusted_tool install)"
CAT_BIN="$(resolve_trusted_tool cat)"
ENV_BIN="$(resolve_trusted_tool env)"

umask 077
trusted_root="$("$MKTEMP_BIN" -d "${RUNNER_TEMP%/}/tin2851-rbe.XXXXXX")"
trap '"$RM_BIN" -rf "$trusted_root"' EXIT
"$MKDIR_BIN" -p "$trusted_root/bootstrap" "$trusted_root/bin" "$trusted_root/home" \
  "$trusted_root/bazelisk-home" "$trusted_root/output-user-root" \
  "$trusted_root/symlinks"

loaded_run="$repo_root/scripts/routine-rbe-run.sh"
loaded_guard="$repo_root/scripts/routine-rbe-guard.py"
loaded_toolchain="$repo_root/config/routine-rbe-toolchain.json"
verify_sha256 "$loaded_run" "$ROUTINE_RBE_RUN_SHA256" "loaded run helper"
verify_sha256 "$loaded_guard" "$ROUTINE_RBE_GUARD_SHA256" "loaded guard helper"
verify_sha256 "$loaded_toolchain" "$ROUTINE_RBE_TOOLCHAIN_SHA256" "loaded toolchain manifest"

python_archive="$trusted_root/bootstrap/python.tar.gz"
download_exact "$ROUTINE_RBE_PYTHON_URL" "$python_archive"
verify_sha256 "$python_archive" "$ROUTINE_RBE_PYTHON_SHA256" "standalone Python archive"
"$TAR_BIN" -xzf "$python_archive" -C "$trusted_root/bootstrap"
python_bin="$trusted_root/bootstrap/python/bin/python3"
[[ -x $python_bin ]] || die "pinned standalone Python executable is missing after extraction"
python_binary_sha256="$(sha256_path "$python_bin")"

trust_state="$trusted_root/trust-state.json"
"$python_bin" -I -S "$loaded_guard" trust-resolve \
  --workspace "$workspace" \
  --trusted-root "$trusted_root/source" \
  --git-path "$GIT_BIN" \
  --action-repository "$ROUTINE_RBE_ACTION_REPOSITORY" \
  --action-ref "$ROUTINE_RBE_ACTION_REF" \
  --workflow-ref "$ROUTINE_RBE_WORKFLOW_REF" \
  --workflow-sha "$ROUTINE_RBE_WORKFLOW_SHA" \
  --workflow-repository "$ROUTINE_RBE_WORKFLOW_REPOSITORY" \
  --workflow-file-path "$ROUTINE_RBE_WORKFLOW_FILE_PATH" \
  --job-workflow-ref "$ROUTINE_RBE_JOB_WORKFLOW_REF" \
  --job-workflow-sha "$ROUTINE_RBE_JOB_WORKFLOW_SHA" \
  --job-workflow-repository "$ROUTINE_RBE_JOB_WORKFLOW_REPOSITORY" \
  --job-workflow-file-path "$ROUTINE_RBE_JOB_WORKFLOW_FILE_PATH" \
  --run-sha256 "$ROUTINE_RBE_RUN_SHA256" \
  --guard-sha256 "$ROUTINE_RBE_GUARD_SHA256" \
  --toolchain-sha256 "$ROUTINE_RBE_TOOLCHAIN_SHA256" \
  --python-url "$ROUTINE_RBE_PYTHON_URL" \
  --python-sha256 "$ROUTINE_RBE_PYTHON_SHA256" \
  --state-out "$trust_state"

canonical_root="$trusted_root/source/canonical-source"
canonical_guard="$canonical_root/scripts/routine-rbe-guard.py"
canonical_toolchain="$canonical_root/config/routine-rbe-toolchain.json"

mapfile -t toolchain_values < <(
  "$python_bin" -I -S - "$canonical_toolchain" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(data["bazelisk"]["url"])
print(data["bazelisk"]["sha256"])
print(data["bazelisk"]["version"])
print(data["bazel"]["version"])
print(data["bazel"]["sha256"])
PY
)
[[ ${#toolchain_values[@]} -eq 5 ]] || die "canonical toolchain manifest is incomplete"
bazelisk_url="${toolchain_values[0]}"
bazelisk_sha256="${toolchain_values[1]}"
bazelisk_version="${toolchain_values[2]}"
bazel_version="${toolchain_values[3]}"
bazel_sha256="${toolchain_values[4]}"

bazelisk_bin="$trusted_root/bin/bazelisk"
download_exact "$bazelisk_url" "$bazelisk_bin"
verify_sha256 "$bazelisk_bin" "$bazelisk_sha256" "Bazelisk binary"
"$CHMOD_BIN" 0500 "$bazelisk_bin"

runtime_path="$trusted_root/bin:$trusted_root/bootstrap/python/bin:$SAFE_SYSTEM_PATH"
CLEAN_ENV=(
  "HOME=$trusted_root/home"
  "PATH=$runtime_path"
  "TMPDIR=$trusted_root/tmp"
  "LANG=C.UTF-8"
  "LC_ALL=C.UTF-8"
  "CI=true"
  "BAZELISK_HOME=$trusted_root/bazelisk-home"
  "BAZELISK_SKIP_WRAPPER=true"
  "BAZELISK_SHOW_PROGRESS=no"
  "USE_BAZEL_VERSION=$bazel_version"
  "BAZELISK_VERIFY_SHA256=$bazel_sha256"
  "PYTHONDONTWRITEBYTECODE=1"
)
"$MKDIR_BIN" -p "$trusted_root/tmp"
for name in SSL_CERT_FILE SSL_CERT_DIR NIX_SSL_CERT_FILE \
  ACTIONS_ID_TOKEN_REQUEST_URL ACTIONS_ID_TOKEN_REQUEST_TOKEN; do
  append_if_set "$name"
done

run_bazelisk() {
  "$ENV_BIN" -i "${CLEAN_ENV[@]}" "$bazelisk_bin" "$@"
}

# Force Bazelisk to materialize the exact Bazel binary and verify its hash
# before any consumer MODULE/BUILD source is loaded.
run_bazelisk version >/dev/null
downloaded_bazel="$("$FIND_BIN" "$trusted_root/bazelisk-home" -type f -path "*/bazel-${bazel_version}-linux-x86_64/bin/bazel" -print -quit)"
[[ -n $downloaded_bazel && -f $downloaded_bazel ]] ||
  die "Bazelisk did not materialize the pinned Bazel ${bazel_version} binary"
verify_sha256 "$downloaded_bazel" "$bazel_sha256" "Bazel binary"
bazel_binary_sha256="$(sha256_path "$downloaded_bazel")"

snapshot="$trusted_root/source-snapshot.json"
"$python_bin" -I -S "$canonical_guard" source-scan \
  --workspace "$workspace" \
  --lanes-path "$ROUTINE_RBE_LANES_PATH" \
  --lane "$ROUTINE_RBE_LANE" \
  --target-class "$ROUTINE_RBE_TARGET_CLASS" \
  --target "$ROUTINE_RBE_TARGET" \
  --bazel-command "$ROUTINE_RBE_BAZEL_COMMAND" \
  --snapshot-out "$snapshot"

mapfile -t attestation_flags < <(
  "$python_bin" -I -S "$canonical_guard" attestation-args \
    --snapshot "$snapshot" \
    --trust-state "$trust_state"
)
[[ ${#attestation_flags[@]} -eq 14 ]] ||
  die "canonical guard emitted an incomplete identity/source attestation"

startup_args=(
  --nosystem_rc
  --nohome_rc
  --noworkspace_rc
  --output_user_root="$trusted_root/output-user-root"
)
if [[ -f "$workspace/.bazelrc" ]]; then
  startup_args+=(--bazelrc="$workspace/.bazelrc")
fi

cd "$workspace"
for required_tag in flywheel-eligible "$ROUTINE_RBE_TARGET_CLASS"; do
  query_output="$(
    run_bazelisk "${startup_args[@]}" query \
      "attr(tags, '^${required_tag}$', ${ROUTINE_RBE_TARGET})" \
      --lockfile_mode=error --output=label 2>"$trusted_root/bazel-query.log"
  )"
  [[ $query_output == "$ROUTINE_RBE_TARGET" ]] ||
    die "target $ROUTINE_RBE_TARGET must carry the exact $required_tag tag"
done
"$python_bin" -I -S "$canonical_guard" source-verify \
  --workspace "$workspace" --snapshot "$snapshot"

remote_args=(
  --remote_cache="$BAZEL_REMOTE_CACHE"
  --remote_executor="$BAZEL_REMOTE_EXECUTOR"
  --remote_upload_local_results=false
  --remote_accept_cached=false
  --remote_local_fallback=false
  --spawn_strategy=remote
  --workspace_status_command=
  --remote_default_exec_properties=gf.platform=gloriousflywheel-rbe-linux-x86_64
)
if [[ -n ${BAZEL_REMOTE_INSTANCE_NAME:-} ]]; then
  [[ $BAZEL_REMOTE_INSTANCE_NAME =~ ^[A-Za-z0-9._/-]+$ ]] ||
    die "BAZEL_REMOTE_INSTANCE_NAME contains unsupported characters"
  remote_args+=(--remote_instance_name="$BAZEL_REMOTE_INSTANCE_NAME")
fi
if [[ -n ${BAZEL_CREDENTIAL_HELPER:-} ]]; then
  [[ $BAZEL_CREDENTIAL_HELPER == /* && -x $BAZEL_CREDENTIAL_HELPER ]] ||
    die "BAZEL_CREDENTIAL_HELPER must be an absolute executable"
  [[ $BAZEL_CREDENTIAL_HELPER != "$workspace"/* ]] ||
    die "consumer-workspace credential helpers are forbidden"
  remote_args+=(--credential_helper="$BAZEL_CREDENTIAL_HELPER")
fi
while IFS= read -r value; do
  [[ -z $value ]] || remote_args+=(--remote_header="$value")
done <<<"${BAZEL_REMOTE_HEADER:-}"
while IFS= read -r value; do
  [[ -z $value ]] || remote_args+=(--remote_cache_header="$value")
done <<<"${BAZEL_REMOTE_CACHE_HEADER:-}"
while IFS= read -r value; do
  [[ -z $value ]] || remote_args+=(--remote_exec_header="$value")
done <<<"${BAZEL_REMOTE_EXEC_HEADER:-}"

bep="$trusted_root/routine-rbe.bep.json"
bazel_log="$trusted_root/routine-rbe.log"
command_args=(
  "${startup_args[@]}"
  "$ROUTINE_RBE_BAZEL_COMMAND"
  "$ROUTINE_RBE_TARGET"
  --config=flywheel-executor
  "${remote_args[@]}"
  --disk_cache=
  --lockfile_mode=error
  --remote_download_minimal
  --symlink_prefix="$trusted_root/symlinks/"
  --build_event_json_file="$bep"
  "${attestation_flags[@]}"
  --verbose_failures
)
if [[ $ROUTINE_RBE_BAZEL_COMMAND == test ]]; then
  command_args+=(--nocache_test_results)
fi

echo "::group::Guarded routine RBE: $ROUTINE_RBE_TARGET_CLASS $ROUTINE_RBE_TARGET"
set +e
run_bazelisk "${command_args[@]}" 2>&1 | "$TEE_BIN" "$bazel_log"
bazel_status=${PIPESTATUS[0]}
set -e
echo "::endgroup::"
[[ $bazel_status -eq 0 ]] || die "guarded Bazel invocation failed with exit $bazel_status"

"$python_bin" -I -S "$canonical_guard" source-verify \
  --workspace "$workspace" --snapshot "$snapshot"
"$python_bin" -I -S "$canonical_guard" trust-recheck --state "$trust_state"
verify_sha256 "$python_archive" "$ROUTINE_RBE_PYTHON_SHA256" "standalone Python archive after execution"
[[ $(sha256_path "$python_bin") == "$python_binary_sha256" ]] ||
  die "standalone Python executable mutated after source scan"
verify_sha256 "$bazelisk_bin" "$bazelisk_sha256" "Bazelisk binary after execution"
[[ $(sha256_path "$downloaded_bazel") == "$bazel_binary_sha256" ]] ||
  die "Bazel binary mutated after source scan"

evidence_tmp="$trusted_root/routine-rbe-evidence.json"
"$python_bin" -I -S "$canonical_guard" evidence-verify \
  --bep "$bep" \
  --snapshot "$snapshot" \
  --trust-state "$trust_state" \
  --toolchain-manifest "$canonical_toolchain" \
  --lane "$ROUTINE_RBE_LANE" \
  --target-class "$ROUTINE_RBE_TARGET_CLASS" \
  --target "$ROUTINE_RBE_TARGET" \
  --bazel-command "$ROUTINE_RBE_BAZEL_COMMAND" \
  --evidence-out "$evidence_tmp"

evidence_path="${RUNNER_TEMP%/}/routine-rbe-evidence-${GITHUB_RUN_ID:-manual}-${ROUTINE_RBE_LANE}.json"
"$INSTALL_BIN" -m 0600 "$evidence_tmp" "$evidence_path"
remote_processes="$(
  "$python_bin" -I -S - "$evidence_path" <<'PY'
import json
import pathlib
import sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["remote_processes"])
PY
)"

if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  {
    echo "proved=true"
    echo "remote-processes=$remote_processes"
    echo "evidence-path=$evidence_path"
  } >>"$GITHUB_OUTPUT"
fi
if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  "$CAT_BIN" >>"$GITHUB_STEP_SUMMARY" <<EOF
### Bounded routine RBE evidence

- Target class: \`$ROUTINE_RBE_TARGET_CLASS\`
- Target: \`$ROUTINE_RBE_TARGET\`
- Remote processes: \`$remote_processes\`
- Scope: one guarded invocation; not package authority, cache attachment, ARC placement, or product-wide RBE readiness
EOF
fi
