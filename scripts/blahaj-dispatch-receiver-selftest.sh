#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
dispatch="${root}/scripts/blahaj-repository-dispatch.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

mkdir -p "${tmp}/bin"
mock_log="${tmp}/gh-calls.log"
payload="${tmp}/payload.json"
sentinel="${tmp}/receiver-command-ran"
printf '{}\n' > "${payload}"

printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'printf "%s\n" "$@" >> "${GH_CALL_LOG}"' \
  'exit "${GH_MOCK_EXIT:-0}"' \
  > "${tmp}/bin/gh"
chmod +x "${tmp}/bin/gh"

run_dispatch() {
  PATH="${tmp}/bin:${PATH}" \
    GH_TOKEN="receiver-containment-selftest" \
    GH_CALL_LOG="${mock_log}" \
    bash "${dispatch}" "$@"
}

: > "${mock_log}"
run_dispatch "tinyland-inc/blahaj" "${payload}"
if [[ "$(grep -Fxc "/repos/tinyland-inc/blahaj/dispatches" "${mock_log}")" -ne 1 ]]; then
  echo "FAIL: exact Blahaj receiver did not reach the mocked gh dispatch endpoint once" >&2
  exit 1
fi

hostile_receiver="tinyland-inc/blahaj'; \$(touch ${sentinel}); #\"\`touch ${sentinel}-tick\`"
hostile_receiver+=$'\nsecond-line'
bad_receivers=(
  "tinyland-inc/not-blahaj"
  "Tinyland-inc/blahaj"
  "tinyland-inc/blahaj/"
  "tinyland-inc/blahaj\$(touch ${sentinel})"
  "${hostile_receiver}"
)
for receiver in "${bad_receivers[@]}"; do
  : > "${mock_log}"
  if run_dispatch "${receiver}" "${payload}" >/dev/null 2>&1; then
    echo "FAIL: invalid receiver was accepted: ${receiver}" >&2
    exit 1
  fi
  if [[ -s "${mock_log}" ]]; then
    echo "FAIL: invalid receiver reached mocked gh: ${receiver}" >&2
    exit 1
  fi
done
if [[ -e "${sentinel}" ]]; then
  echo "FAIL: receiver input was evaluated as shell code" >&2
  exit 1
fi

: > "${mock_log}"
PATH="${tmp}/bin:${PATH}" \
  GH_TOKEN="receiver-containment-selftest" \
  GH_CALL_LOG="${mock_log}" \
  GH_MOCK_EXIT=7 \
  bash "${dispatch}" "tinyland-inc/blahaj" "${payload}" best-effort >/dev/null
if [[ "$(grep -Fxc "/repos/tinyland-inc/blahaj/dispatches" "${mock_log}")" -ne 1 ]]; then
  echo "FAIL: best-effort dispatch did not invoke mocked gh exactly once" >&2
  exit 1
fi

echo "Blahaj repository_dispatch receiver self-test passed"
