#!/usr/bin/env bash

set -euo pipefail

readonly API_VERSION="2026-03-10"

die() {
  printf '::error::%s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

api_get() {
  local endpoint="$1"
  GH_TOKEN="$token" gh api \
    --method GET \
    --header "Accept: application/vnd.github+json" \
    --header "X-GitHub-Api-Version: ${API_VERSION}" \
    "$endpoint"
}

repository="${IMMUTABLE_RELEASE_REPOSITORY:-}"
source_run_id="${IMMUTABLE_RELEASE_SOURCE_RUN_ID:-}"
observer_sha="${IMMUTABLE_RELEASE_OBSERVER_SHA:-}"
expected_workflow_path="${IMMUTABLE_RELEASE_SOURCE_WORKFLOW_PATH:-}"
expected_workflow_name="${IMMUTABLE_RELEASE_SOURCE_WORKFLOW_NAME:-}"
expected_artifact_name="${IMMUTABLE_RELEASE_ARTIFACT_NAME:-immutable-release-package}"
token="${IMMUTABLE_RELEASE_TOKEN:-}"

unset IMMUTABLE_RELEASE_TOKEN GH_TOKEN

[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
  die "repository must be an owner/name coordinate"
[[ "$source_run_id" =~ ^[1-9][0-9]*$ ]] || die "source run id must be a positive integer"
observer_sha="$(printf '%s' "$observer_sha" | tr '[:upper:]' '[:lower:]')"
[[ "$observer_sha" =~ ^[0-9a-f]{40}$ ]] ||
  die "observer SHA must be a full lowercase 40-character commit SHA"
[[ "$expected_workflow_path" =~ ^\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml$ ]] ||
  die "expected workflow path must be a repository-relative workflow YAML path"
[[ -n "$expected_workflow_name" ]] || die "expected workflow name is required"
[[ "$expected_artifact_name" =~ ^[A-Za-z0-9_.-]+$ ]] ||
  die "expected artifact name contains unsupported characters"
[[ -n "$token" ]] || die "a read-only GitHub token is required"

require_command gh
require_command jq

repo_json="$(api_get "repos/$repository")" || die "cannot read repository metadata"
default_branch="$(jq -er '.default_branch | select(type == "string" and length > 0)' <<<"$repo_json")" ||
  die "repository metadata is missing default_branch"
repository_id="$(jq -er '.id | select(type == "number") | tostring' <<<"$repo_json")" ||
  die "repository metadata is missing id"

encoded_default_branch="$(jq -nr --arg value "$default_branch" '$value | @uri')"
branch_json="$(api_get "repos/$repository/branches/$encoded_default_branch")" ||
  die "cannot read the live default branch"
if ! jq -e '.protected == true' >/dev/null <<<"$branch_json"; then
  die "live default branch $default_branch is not protected"
fi
current_default_sha="$(
  jq -er '.commit.sha | select(type == "string") | ascii_downcase' <<<"$branch_json"
)" || die "default branch response is missing commit.sha"
[[ "$current_default_sha" =~ ^[0-9a-f]{40}$ ]] || die "default branch returned an invalid SHA"
[[ "$current_default_sha" == "$observer_sha" ]] ||
  die "observer workflow source $observer_sha is not current protected $default_branch $current_default_sha"

run_json="$(api_get "repos/$repository/actions/runs/$source_run_id")" ||
  die "cannot read source workflow run $source_run_id"
if ! jq -e \
  --argjson run_id "$source_run_id" \
  --arg repository "$repository" \
  --arg workflow_path "$expected_workflow_path" \
  --arg workflow_name "$expected_workflow_name" '
    (.id == $run_id)
    and ((.repository.full_name // "" | ascii_downcase) == ($repository | ascii_downcase))
    and ((.head_repository.full_name // "" | ascii_downcase) == ($repository | ascii_downcase))
    and (.event == "release")
    and (.status == "completed")
    and (.conclusion == "success")
    and (.path == $workflow_path)
    and (.name == $workflow_name)
    and (.workflow_id | type == "number")
    and (.run_attempt | type == "number" and . >= 1)
    and (.head_sha | type == "string")
    and (.head_branch | type == "string")
  ' >/dev/null <<<"$run_json"; then
  die "source run is not a successful release event from the exact trusted workflow"
fi
source_sha="$(jq -er '.head_sha | ascii_downcase' <<<"$run_json")"
release_tag="$(jq -er '.head_branch' <<<"$run_json")"
source_run_attempt="$(jq -er '.run_attempt' <<<"$run_json")"
workflow_id="$(jq -er '.workflow_id' <<<"$run_json")"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || die "source run returned an invalid head SHA"
[[ "$source_sha" == "$observer_sha" ]] ||
  die "source run head $source_sha does not equal trusted observer/default source $observer_sha"
[[ "$release_tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
  die "source run tag must be canonical stable SemVer vMAJOR.MINOR.PATCH"

commit_json="$(api_get "repos/$repository/commits/$source_sha")" ||
  die "cannot read source commit verification"
if ! jq -e \
  --arg source_sha "$source_sha" '
    ((.sha | ascii_downcase) == $source_sha)
    and .commit.verification.verified == true
    and .commit.verification.reason == "valid"
    and (.commit.verification.signature | type == "string" and length > 0)
    and (.commit.verification.payload | type == "string" and length > 0)
  ' >/dev/null <<<"$commit_json"; then
  die "source commit $source_sha is not GitHub-verified and signed"
fi

workflow_json="$(api_get "repos/$repository/actions/workflows/$workflow_id")" ||
  die "cannot read source workflow identity"
if ! jq -e \
  --arg workflow_path "$expected_workflow_path" \
  --arg workflow_name "$expected_workflow_name" '
    .path == $workflow_path and .name == $workflow_name and .state == "active"
  ' >/dev/null <<<"$workflow_json"; then
  die "source run workflow id does not resolve to the expected active workflow"
fi

artifacts_json="$(api_get "repos/$repository/actions/runs/$source_run_id/artifacts?per_page=100")" ||
  die "cannot list source-run artifacts"
artifact_count="$(jq -er --arg name "$expected_artifact_name" '[.artifacts[]? | select(.name == $name)] | length' <<<"$artifacts_json")"
[[ "$artifact_count" == "1" ]] ||
  die "source run must contain exactly one $expected_artifact_name artifact, found $artifact_count"
artifact_id="$(jq -er --arg name "$expected_artifact_name" '.artifacts[] | select(.name == $name) | .id' <<<"$artifacts_json")"
artifact_json="$(api_get "repos/$repository/actions/artifacts/$artifact_id")" ||
  die "cannot read candidate artifact $artifact_id"
if ! jq -e \
  --argjson artifact_id "$artifact_id" \
  --arg name "$expected_artifact_name" \
  --argjson run_id "$source_run_id" \
  --arg source_sha "$source_sha" '
    (.id == $artifact_id)
    and (.name == $name)
    and (.expired == false)
    and (.digest | type == "string" and test("^sha256:[0-9a-f]{64}$"))
    and (.workflow_run.id == $run_id)
    and ((.workflow_run.head_sha | ascii_downcase) == $source_sha)
  ' >/dev/null <<<"$artifact_json"; then
  die "candidate artifact is expired, malformed, or bound to another source run/head"
fi
artifact_digest="$(jq -er '.digest' <<<"$artifact_json")"

encoded_tag="$(jq -nr --arg value "$release_tag" '$value | @uri')"
tag_ref_json="$(api_get "repos/$repository/git/ref/tags/$encoded_tag")" ||
  die "exact release tag ref is unavailable: $release_tag"
if ! jq -e '.object.type == "tag" and (.object.sha | type == "string")' >/dev/null <<<"$tag_ref_json"; then
  die "$release_tag must be an annotated tag, not a lightweight or nested ref"
fi
tag_object_sha="$(jq -er '.object.sha | ascii_downcase' <<<"$tag_ref_json")"
[[ "$tag_object_sha" =~ ^[0-9a-f]{40}$ ]] || die "tag ref returned an invalid object SHA"

tag_object_json="$(api_get "repos/$repository/git/tags/$tag_object_sha")" ||
  die "cannot read annotated tag object $tag_object_sha"
if ! jq -e \
  --arg tag "$release_tag" \
  --arg source_sha "$source_sha" '
    .tag == $tag
    and .object.type == "commit"
    and ((.object.sha | ascii_downcase) == $source_sha)
    and .verification.verified == true
    and .verification.reason == "valid"
    and (.verification.signature | type == "string" and length > 0)
    and (.verification.payload | type == "string" and length > 0)
  ' >/dev/null <<<"$tag_object_json"; then
  die "$release_tag is not a GitHub-verified signed annotated tag targeting $source_sha"
fi

release_json="$(api_get "repos/$repository/releases/tags/$encoded_tag")" ||
  die "published GitHub Release is unavailable for $release_tag"
if ! jq -e \
  --arg tag "$release_tag" '
    .tag_name == $tag
    and .draft == false
    and .prerelease == false
    and .immutable == true
    and (.published_at | type == "string" and length > 0)
    and (.id | type == "number")
  ' >/dev/null <<<"$release_json"; then
  die "GitHub Release must be live, stable, immutable, and tag-matched"
fi
release_id="$(jq -er '.id | tostring' <<<"$release_json")"

if ! attestation_json="$(
  GH_TOKEN="$token" gh release verify \
    --repo "$repository" \
    --format json \
    -- "$release_tag"
)"; then
  die "release attestation is absent or failed cryptographic verification for $repository@$release_tag"
fi
if ! jq -e \
  --arg repository "$repository" \
  --arg repository_id "$repository_id" \
  --arg release_id "$release_id" \
  --arg tag "$release_tag" \
  --arg tag_object_sha "$tag_object_sha" '
    .verificationResult.statement as $statement
    | ($statement.predicate // {}) as $predicate
    | ($predicate.purl // "") as $purl
    | ($statement._type == "https://in-toto.io/Statement/v1")
      and ($statement.predicateType == "https://in-toto.io/attestation/release/v0.2")
      and (($predicate.repository // "" | ascii_downcase) == ($repository | ascii_downcase))
      and (($predicate.repositoryId // "" | tostring) == $repository_id)
      and (($predicate.databaseId // "" | tostring) == $release_id)
      and ($predicate.tag == $tag)
      and ($purl != "")
      and any(
        $statement.subject[]?;
        ((.uri // "") == $purl)
        and ((.digest.sha1 // "" | ascii_downcase) == $tag_object_sha)
      )
  ' >/dev/null <<<"$attestation_json"; then
  die "verified release attestation does not bind repository/release/tag object exactly"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    printf 'artifact-id=%s\n' "$artifact_id"
    printf 'artifact-digest=%s\n' "$artifact_digest"
    printf 'source-sha=%s\n' "$source_sha"
    printf 'source-run-attempt=%s\n' "$source_run_attempt"
    printf 'release-tag=%s\n' "$release_tag"
    printf 'tag-object-sha=%s\n' "$tag_object_sha"
    printf 'release-id=%s\n' "$release_id"
  } >>"$GITHUB_OUTPUT"
fi

unset token
printf '::notice::trusted immutable release verified (repository=%s, tag=%s, source=%s, artifact=%s)\n' \
  "$repository" "$release_tag" "$source_sha" "$artifact_id"
