#!/usr/bin/env bash
set -euo pipefail

readonly expected_receiver="tinyland-inc/blahaj"

if [[ $# -ne 1 ]]; then
  echo "::error::usage: validate-blahaj-dispatch-receiver.sh <owner/repository>" >&2
  exit 64
fi

receiver="$1"
if [[ "${receiver}" != "${expected_receiver}" ]]; then
  printf '::error::repository_dispatch receiver must be exactly %s\n' \
    "${expected_receiver}" >&2
  exit 64
fi
