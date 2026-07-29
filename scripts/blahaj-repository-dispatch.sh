#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: blahaj-repository-dispatch.sh <receiver> <payload-path> [strict|best-effort]" >&2
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 64
fi

receiver="$1"
payload_path="$2"
failure_mode="${3:-strict}"

case "${failure_mode}" in
  strict|best-effort) ;;
  *)
    usage
    exit 64
    ;;
esac

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "${script_dir}/validate-blahaj-dispatch-receiver.sh" "${receiver}"

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error::dispatch_token is required for repository_dispatch" >&2
  exit 64
fi
if [[ ! -f "${payload_path}" ]]; then
  echo "::error::repository_dispatch payload does not exist" >&2
  exit 66
fi

set +e
gh api "/repos/${receiver}/dispatches" \
  -X POST \
  -H "Accept: application/vnd.github+json" \
  --input "${payload_path}"
dispatch_status=$?
set -e

if [[ ${dispatch_status} -ne 0 ]]; then
  if [[ "${failure_mode}" == "best-effort" ]]; then
    echo "::warning::Blahaj dispatch failed; reap is idempotent and the hourly TTL backstop will retry"
    exit 0
  fi
  exit "${dispatch_status}"
fi
