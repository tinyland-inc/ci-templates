#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

mkdir -p "${tmp}/bin" "${tmp}/runner"
gh_log="${tmp}/gh-calls.log"
sentinel="${tmp}/executed"
: > "${gh_log}"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'printf "%s\n" "$@" >> "${GH_CALL_LOG}"' \
  'exit 99' \
  > "${tmp}/bin/gh"
chmod +x "${tmp}/bin/gh"

extract_step() {
  local action_path="$1"
  local step_name="$2"
  local output_path="$3"
  ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    step = doc.fetch("runs").fetch("steps").find { |candidate| candidate["name"] == ARGV[1] }
    abort("missing step #{ARGV[1]} in #{ARGV[0]}") unless step && step["run"]
    File.write(ARGV[2], step.fetch("run"))
  ' "${action_path}" "${step_name}" "${output_path}"
}

run_step() {
  local script_path="$1"
  shift
  local output_path="${tmp}/github-output"
  : > "${output_path}"
  env \
    PATH="${tmp}/bin:${PATH}" \
    GH_CALL_LOG="${gh_log}" \
    RUNNER_TEMP="${tmp}/runner" \
    GITHUB_OUTPUT="${output_path}" \
    GITHUB_RUN_ID="424242" \
    "$@" \
    bash "${script_path}" >/dev/null
}

attack="'; touch ${sentinel}; #\"\$(touch ${sentinel}-sub)\`touch ${sentinel}-tick\`"
attack+=$'\nsecond-line'
lanes_json="$(jq -nc --arg value "${attack}" \
  '[{name:"acuity", theme:$value, snapshot_source:$value}]')"
labels_json="$(jq -nc --arg value "${attack}" '[$value]')"
emails_json="$(jq -nc --arg value "${attack}" '[$value]')"

lane_dispatch_step="${tmp}/lane-dispatch-build.sh"
extract_step \
  "${root}/.github/actions/lane-dispatch/action.yml" \
  "Build payload" \
  "${lane_dispatch_step}"
run_step "${lane_dispatch_step}" \
  "PR_NUMBER=17" \
  "COMMIT_SHA=0123456789abcdef0123456789abcdef01234567" \
  "SPOKE=safe-spoke" \
  "DOMAIN=${attack}" \
  "IMAGE_REF=${attack}" \
  "LANES_JSON=${lanes_json}" \
  "TTL_LABEL_PREFIX=${attack}" \
  "PR_LABELS_JSON=${labels_json}"

lane_reap_step="${tmp}/lane-reap-build.sh"
extract_step \
  "${root}/.github/actions/lane-reap/action.yml" \
  "Build destroy payload" \
  "${lane_reap_step}"
run_step "${lane_reap_step}" \
  "PR_NUMBER=17" \
  "SPOKE=safe-spoke" \
  "DOMAIN=${attack}" \
  "COMMIT_SHA=0123456789abcdef0123456789abcdef01234567" \
  "LANES_JSON=${lanes_json}"

lane_ttl_step="${tmp}/lane-ttl-reap-build.sh"
extract_step \
  "${root}/.github/actions/lane-ttl-reap/action.yml" \
  "Build TTL reap payload" \
  "${lane_ttl_step}"
run_step "${lane_ttl_step}" \
  "SPOKE=safe-spoke" \
  "DOMAIN=${attack}" \
  "DRY_RUN=false"

public_preview_step="${tmp}/public-preview-build.sh"
extract_step \
  "${root}/.github/actions/public-preview-dispatch/action.yml" \
  "Build payload" \
  "${public_preview_step}"
run_step "${public_preview_step}" \
  "OPERATION=provision" \
  "SPOKE=safe-spoke" \
  "SOURCE_REPOSITORY=${attack}" \
  "SOURCE_PR=17" \
  "SOURCE_COMMIT=0123456789abcdef0123456789abcdef01234567" \
  "LANE=${attack}" \
  "ORIGIN_FQDN=${attack}" \
  "ORIGIN_SERVICE=${attack}" \
  "ORIGIN_HOST_HEADER=${attack}" \
  "PREVIEW_HOSTNAME=${attack}" \
  "TTL_HOURS=72" \
  "DESCRIPTION=${attack}" \
  "ALLOW_EMAILS_JSON=${emails_json}" \
  "ALLOW_EMAIL_DOMAINS_JSON=[]" \
  "SESSION_DURATION=${attack}"

if run_step "${lane_dispatch_step}" \
  "PR_NUMBER=17" \
  "COMMIT_SHA=0123456789abcdef0123456789abcdef01234567" \
  "SPOKE=${attack}" \
  "DOMAIN=example.test" \
  "IMAGE_REF=ghcr.io/example/image:test" \
  "LANES_JSON=${lanes_json}" \
  "TTL_LABEL_PREFIX=lane-ttl/" \
  "PR_LABELS_JSON=[]" 2>/dev/null; then
  echo "FAIL: hostile spoke identifier was accepted" >&2
  exit 1
fi

if find "${tmp}" -maxdepth 1 -name 'executed*' -print -quit | grep -q .; then
  echo "FAIL: an action input was evaluated as shell source" >&2
  exit 1
fi
if [[ -s "${gh_log}" ]]; then
  echo "FAIL: a payload-build step reached mocked gh" >&2
  exit 1
fi

echo "Blahaj dispatch shell-input self-test passed"
