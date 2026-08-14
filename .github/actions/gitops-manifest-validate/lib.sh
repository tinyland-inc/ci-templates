#!/usr/bin/env bash
# gitops-manifest-validate/lib.sh
#
# Shared helper vocabulary sourced by a caller-authored assertions script.
# Extracted VERBATIM (function bodies, not just names) from the identical
# preamble duplicated across great-falls-tool-bus-infra's
# scripts/validate-{mail-crs,form-stack,list-stack,archive-stack,web-stack}.sh
# -- every one of those five files opens with byte-for-byte the same
# fail/require_file/field/assert_eq quartet before diverging into
# stack-specific CR/manifest field assertions.
#
# SUBSTRATE SEAM: this file expresses the ASSERTION VOCABULARY every GFTB/MMS
# manifest validator already uses (fail loudly, require a file, read a yq
# field, assert equality) plus the two invariants that are true of every
# k8s/<stack> overlay regardless of domain (digest-pinned images, a
# kustomize tree that renders). It does NOT know what a MailAccount or a
# Deployment replica count SHOULD be for any given tenant -- those
# assertions stay caller-authored, because they are the one part of each
# validator that is genuinely tenant-specific and must never be templated
# away. Absorbing them here would be the R172-R174 anti-pattern this
# extraction is explicitly ratified against.

set -euo pipefail

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  test -f "${path}" || fail "missing ${path}"
}

field() {
  local expr="$1"
  local path="$2"
  yq -r "${expr}" "${path}"
}

assert_eq() {
  local got="$1"
  local want="$2"
  local label="$3"
  if [ "${got}" != "${want}" ]; then
    fail "${label}: got '${got}', want '${want}'"
  fi
}

require_tools() {
  # Every one of the five source validators repeats this pair; web-stack.sh
  # and form-stack.sh additionally require jq for bot-policy JSON assertions,
  # which stays caller-invoked (require_tools jq) rather than assumed here.
  local tool
  for tool in "$@"; do
    command -v "${tool}" >/dev/null 2>&1 || fail "${tool} is required"
  done
  command -v yq >/dev/null 2>&1 || fail "yq is required"
  command -v kubectl >/dev/null 2>&1 || fail "kubectl is required for kubectl kustomize"
}

# --- Universal invariant 1: every image line is digest-pinned ---------------
# Byte-identical check duplicated in all five source validators. A stack that
# has no image: lines at all (pure-CR stacks like mail-crs) simply matches
# nothing here, which is correct -- it is not exempted, it has nothing to
# check.
assert_images_digest_pinned() {
  local dir="$1"
  if grep -REn "image:\s*\S*:latest" "${dir}" >/dev/null 2>&1; then
    fail "images must be pinned by digest, not :latest"
  fi
  local line
  while IFS= read -r line; do
    case "${line}" in
    *"@sha256:"*) : ;;
    *) fail "image not pinned by digest: ${line}" ;;
    esac
  done < <(grep -REh "^\s*image:\s*\S+" "${dir}" 2>/dev/null || true)
}

# --- Universal invariant 2: the kustomize tree renders -----------------------
# Every source validator's final line. A manifest set that assert_eq's
# perfectly but does not kustomize-render is not actually deployable; this
# is the one check that catches that gap regardless of stack shape.
assert_kustomize_renders() {
  local dir="$1"
  kubectl kustomize "${dir}" >/dev/null
}
