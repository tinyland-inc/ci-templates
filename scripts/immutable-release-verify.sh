#!/usr/bin/env bash

set -euo pipefail

readonly API_VERSION="2026-03-10"
readonly DEFAULT_VERIFY_ATTEMPTS="5"
readonly DEFAULT_VERIFY_RETRY_SECONDS="3"

die() {
  printf '::error::%s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

normalize_sha() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

validate_sha() {
  local sha="$1"
  [[ "$sha" =~ ^[0-9a-f]{40}$ || "$sha" =~ ^[0-9a-f]{64}$ ]]
}

api_get() {
  local token="$1"
  local endpoint="$2"

  GH_TOKEN="$token" gh api \
    --method GET \
    --header "Accept: application/vnd.github+json" \
    --header "X-GitHub-Api-Version: ${API_VERSION}" \
    "$endpoint"
}

mode="${IMMUTABLE_RELEASE_MODE:-}"
repository="${IMMUTABLE_RELEASE_REPOSITORY:-}"
tag="${IMMUTABLE_RELEASE_TAG:-}"
expected_source_sha_raw="${IMMUTABLE_RELEASE_EXPECTED_SOURCE_SHA:-}"
admin_token="${IMMUTABLE_RELEASE_ADMIN_TOKEN:-}"
contents_token="${IMMUTABLE_RELEASE_CONTENTS_TOKEN:-}"
verify_attempts="${IMMUTABLE_RELEASE_VERIFY_ATTEMPTS:-$DEFAULT_VERIFY_ATTEMPTS}"
verify_retry_seconds="${IMMUTABLE_RELEASE_VERIFY_RETRY_SECONDS:-$DEFAULT_VERIFY_RETRY_SECONDS}"

# Do not export either credential to any child process by default. Each gh call
# receives exactly the token needed for that one request.
unset IMMUTABLE_RELEASE_ADMIN_TOKEN IMMUTABLE_RELEASE_CONTENTS_TOKEN GH_TOKEN

case "$mode" in
  settings | published) ;;
  *) die "mode must be settings or published" ;;
esac

[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
  die "repository must be an owner/name coordinate"

require_command gh
require_command jq

if [[ "$mode" == "settings" ]]; then
  [[ -n "$admin_token" ]] ||
    die "settings mode requires an Administration-read GitHub App token"
  [[ -z "$contents_token" ]] ||
    die "settings mode does not accept a Contents token"

  settings_endpoint="repos/${repository}/immutable-releases"
  if ! settings_json="$(api_get "$admin_token" "$settings_endpoint")"; then
    unset admin_token
    die "cannot confirm immutable releases for $repository via GET /$settings_endpoint; GitHub documents 404 when the setting is disabled, and inaccessible repositories may also be hidden as 404"
  fi
  unset admin_token

  if ! jq -e 'type == "object" and .enabled == true' >/dev/null <<<"$settings_json"; then
    die "immutable releases are not enabled for $repository"
  fi
  enforced_by_owner="$(
    jq -r 'if .enforced_by_owner == true then "true" else "false" end' <<<"$settings_json"
  )"
  printf '::notice::immutable releases enabled (repository=%s, enforced_by_owner=%s)\n' \
    "$repository" "$enforced_by_owner"

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'immutable-releases-enabled=true\n' >>"$GITHUB_OUTPUT"
  fi
  exit 0
fi

[[ -z "$admin_token" ]] ||
  die "published mode does not accept an Administration token"
[[ -n "$contents_token" ]] ||
  die "published mode requires a Contents-read GitHub token"
[[ -n "$tag" ]] || die "published mode requires an exact release tag"
require_command git
git check-ref-format "refs/tags/$tag" >/dev/null 2>&1 ||
  die "invalid release tag: $tag"
expected_source_sha="$(normalize_sha "$expected_source_sha_raw")"
validate_sha "$expected_source_sha" ||
  die "expected source SHA must be a 40-character SHA-1 or 64-character SHA-256"
[[ "$verify_attempts" =~ ^[1-9][0-9]*$ ]] ||
  die "verify attempts must be a positive integer"
[[ "$verify_retry_seconds" =~ ^[0-9]+$ ]] ||
  die "verify retry seconds must be a non-negative integer"

encoded_tag="$(jq -nr --arg tag "$tag" '$tag | @uri')"
ref_endpoint="repos/${repository}/git/ref/tags/${encoded_tag}"
if ! object_json="$(api_get "$contents_token" "$ref_endpoint")"; then
  die "exact tag ref is unavailable: refs/tags/$tag"
fi

object_type="$(jq -er '.object.type | select(type == "string")' <<<"$object_json")" ||
  die "tag ref response is missing object.type"
object_sha="$(jq -er '.object.sha | select(type == "string")' <<<"$object_json")" ||
  die "tag ref response is missing object.sha"
object_sha="$(normalize_sha "$object_sha")"
validate_sha "$object_sha" || die "tag ref returned an invalid object SHA"

depth=0
seen_tag_objects=""
while [[ "$object_type" == "tag" ]]; do
  depth=$((depth + 1))
  if ((depth > 8)); then
    die "annotated tag chain exceeds the maximum peel depth"
  fi
  case " $seen_tag_objects " in
    *" $object_sha "*) die "annotated tag chain contains a cycle" ;;
  esac
  seen_tag_objects="${seen_tag_objects} ${object_sha}"

  tag_object_endpoint="repos/${repository}/git/tags/${object_sha}"
  if ! object_json="$(api_get "$contents_token" "$tag_object_endpoint")"; then
    die "cannot peel annotated tag object $object_sha"
  fi
  object_type="$(jq -er '.object.type | select(type == "string")' <<<"$object_json")" ||
    die "annotated tag response is missing object.type"
  object_sha="$(jq -er '.object.sha | select(type == "string")' <<<"$object_json")" ||
    die "annotated tag response is missing object.sha"
  object_sha="$(normalize_sha "$object_sha")"
  validate_sha "$object_sha" || die "annotated tag returned an invalid object SHA"
done

[[ "$object_type" == "commit" ]] ||
  die "refs/tags/$tag peels to unsupported Git object type: $object_type"
[[ "$object_sha" == "$expected_source_sha" ]] ||
  die "refs/tags/$tag peels to $object_sha, expected $expected_source_sha"
printf '::notice::exact tag binding verified (tag=%s, source_sha=%s)\n' \
  "$tag" "$object_sha"

if ! gh release verify --help >/dev/null 2>&1; then
  die "installed GitHub CLI does not support cryptographic release-attestation verification"
fi

case "${#object_sha}" in
  40) digest_algorithm="sha1" ;;
  64) digest_algorithm="sha256" ;;
  *) die "unsupported peeled commit digest length" ;;
esac

release_endpoint="repos/${repository}/releases/tags/${encoded_tag}"
attestation_verified="false"
last_retry_error=""
for ((attempt = 1; attempt <= verify_attempts; attempt++)); do
  release_json=""
  if ! release_json="$(api_get "$contents_token" "$release_endpoint")"; then
    last_retry_error="published GitHub Release is unavailable for tag $tag"
  elif ! jq -e --arg tag "$tag" '
    type == "object"
    and .tag_name == $tag
    and .draft == false
    and .published_at != null
  ' >/dev/null <<<"$release_json"; then
    die "GitHub Release for $tag is missing, unpublished, draft, or tag-mismatched"
  elif ! jq -e '.immutable == true' >/dev/null <<<"$release_json"; then
    last_retry_error="GitHub Release for $tag is not yet immutable"
  else
    attestation_json=""
    if ! attestation_json="$(
      GH_TOKEN="$contents_token" gh release verify \
        --repo "$repository" \
        --format json \
        -- "$tag"
    )"; then
      last_retry_error="release attestation is unavailable or failed cryptographic verification for $repository@$tag"
    elif ! jq -e \
      --arg repository "$repository" \
      --arg tag "$tag" \
      --arg digest_algorithm "$digest_algorithm" \
      --arg source_sha "$object_sha" '
        .verificationResult.statement as $statement
        | ($statement.predicate // {}) as $predicate
        | ($predicate.purl // "") as $purl
        | ($statement.predicateType == "https://in-toto.io/attestation/release/v0.2")
          and (($predicate.repository // "" | ascii_downcase) == ($repository | ascii_downcase))
          and ($predicate.tag == $tag)
          and ($purl != "")
          and any(
            $statement.subject[]?;
            ((.uri // "") == $purl)
            and ((.digest[$digest_algorithm] // "" | ascii_downcase) == $source_sha)
          )
      ' >/dev/null <<<"$attestation_json"; then
      die "verified release attestation does not bind $repository@$tag to peeled source $object_sha"
    else
      attestation_verified="true"
      break
    fi
  fi

  if ((attempt < verify_attempts)); then
    printf '::notice::published release verification attempt %d/%d is not ready: %s\n' \
      "$attempt" "$verify_attempts" "$last_retry_error"
    sleep "$verify_retry_seconds"
  fi
done

[[ "$attestation_verified" == "true" ]] ||
  die "published release did not become immutable and attestable after $verify_attempts attempt(s): $last_retry_error"
printf '::notice::release attestation binding verified (repository=%s, tag=%s, source_sha=%s)\n' \
  "$repository" "$tag" "$object_sha"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    printf 'source-sha=%s\n' "$object_sha"
    printf 'release-attestation-verified=%s\n' "$attestation_verified"
  } >>"$GITHUB_OUTPUT"
fi
