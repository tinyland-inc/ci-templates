#!/usr/bin/env bash

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_workflow="${root}/.github/workflows/release.yml"
package_workflow="${root}/.github/workflows/js-bazel-package.yml"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

extract_step() {
  local workflow="$1"
  local job="$2"
  local step="$3"
  ruby -ryaml -e '
    workflow = YAML.load_file(ARGV.fetch(0))
    steps = workflow.fetch("jobs").fetch(ARGV.fetch(1)).fetch("steps")
    selected = steps.find { |candidate| candidate["name"] == ARGV.fetch(2) }
    abort("missing workflow step: #{ARGV.fetch(1)} / #{ARGV.fetch(2)}") unless selected
    puts selected.fetch("run")
  ' "$workflow" "$job" "$step"
}

event_guard="$(extract_step "$package_workflow" resolve-runner 'Require release:published for immutable publication')"
source_step="$(extract_step "$package_workflow" resolve-runner 'Resolve reviewed immutable-release verifier source')"
plan_step="$(extract_step "$release_workflow" release-plan 'Detect release commit')"
version_step="$(extract_step "$release_workflow" publish-version-release 'Cut or reuse exact version tag')"
release_step="$(extract_step "$release_workflow" publish-version-release 'Create or reuse immutable GitHub Release')"
major_step="$(extract_step "$release_workflow" move-floating-major 'Move floating major after published verification')"

pass=0
fail=0

expect_status() {
  local expected="$1"
  local description="$2"
  shift 2
  local actual
  set +e
  "$@" >"$tmp/case.out" 2>&1
  actual=$?
  set -e
  if [[ "$actual" -eq "$expected" ]]; then
    pass=$((pass + 1))
    printf 'ok   [exit %d] %s\n' "$actual" "$description"
  else
    fail=$((fail + 1))
    printf 'FAIL [exit %d, want %d] %s\n' "$actual" "$expected" "$description"
    tail -5 "$tmp/case.out" | sed 's/^/       /'
  fi
}

check_workflow_policy() {
  local release_file="${1:-$release_workflow}"
  local package_file="${2:-$package_workflow}"
  # Ruby compares literal GitHub expressions.
  # shellcheck disable=SC2016
  ruby -ryaml -e '
    release = YAML.load_file(ARGV.fetch(0))
    package = YAML.load_file(ARGV.fetch(1))
    release_text = File.read(ARGV.fetch(0))
    package_text = File.read(ARGV.fetch(1))

    expected_checkout = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    local_release_action = "./.github/actions/immutable-release-verify"
    local_package_action = "./.ci-templates-immutable-release/.github/actions/immutable-release-verify"
    remote_self_action = %r{tinyland-inc/ci-templates/\.github/actions/immutable-release-verify@}

    abort("remote self-action pins can execute a stale verifier tree") if
      (release_text + package_text).match?(remote_self_action)

    concurrency = release.fetch("concurrency")
    abort("release concurrency must retain the supported maximum pending queue") unless concurrency["queue"] == "max"
    abort("release concurrency must not cancel an in-progress transaction") if concurrency["cancel-in-progress"] == true

    abort("manual fallback must be a main-only workflow_dispatch") unless
      release_text.include?("workflow_dispatch:") &&
      release_text.include?("github.event_name == '\''workflow_dispatch'\'' && github.ref == '\''refs/heads/main'\''")

    release_jobs = release.fetch("jobs")
    settings_permissions = release_jobs.fetch("immutable-release-settings").fetch("permissions")
    abort("settings verifier permissions drifted") unless settings_permissions == {"contents" => "read"}
    verify_permissions = release_jobs.fetch("verify-published-release").fetch("permissions")
    abort("release verifier permissions drifted") unless verify_permissions == {
      "attestations" => "read",
      "contents" => "read",
    }

    package_permissions = package.fetch("jobs").fetch("resolve-runner").fetch("permissions")
    abort("package verifier permissions drifted") unless package_permissions == {
      "actions" => "read",
      "attestations" => "read",
      "contents" => "read",
    }

    %w[immutable-release-settings verify-published-release].each do |job_name|
      steps = release_jobs.fetch(job_name).fetch("steps")
      checkout_index = steps.index { |step| step["name"] == "Checkout reviewed verifier source" }
      verifier_index = steps.index { |step| step["uses"] == local_release_action }
      abort("#{job_name} does not execute the planned verifier tree") unless
        checkout_index && verifier_index && checkout_index < verifier_index
      checkout = steps.fetch(checkout_index)
      abort("#{job_name} checkout action is not pinned") unless checkout["uses"] == expected_checkout
      abort("#{job_name} checkout can drift from the planned source") unless
        checkout.fetch("with").fetch("ref") == "${{ needs.release-plan.outputs.source_sha }}"
      abort("#{job_name} checkout persists credentials") unless
        checkout.fetch("with").fetch("persist-credentials") == false
    end

    package_steps = package.fetch("jobs").fetch("resolve-runner").fetch("steps")
    source_index = package_steps.index { |step| step["name"] == "Resolve reviewed immutable-release verifier source" }
    checkout_index = package_steps.index { |step| step["name"] == "Checkout reviewed immutable-release verifier tree" }
    mint_index = package_steps.index { |step| step["name"] == "Mint Administration-read installation token" }
    verifier_indexes = package_steps.each_index.select { |index| package_steps[index]["uses"] == local_package_action }
    abort("package verifier bootstrap ordering drifted") unless
      source_index && checkout_index && mint_index &&
      source_index < checkout_index && checkout_index < mint_index &&
      verifier_indexes.length == 2 && verifier_indexes.all? { |index| checkout_index < index }
    source_run = package_steps.fetch(source_index).fetch("run")
    abort("package verifier source is not bound to run metadata") unless
      source_run.include?(".referenced_workflows[]?") &&
      source_run.include?("reviewed reusable workflow source is absent")
    checkout = package_steps.fetch(checkout_index)
    abort("package verifier checkout action is not pinned") unless checkout["uses"] == expected_checkout
    abort("package verifier checkout can drift from the resolved workflow SHA") unless
      checkout.fetch("with").fetch("ref") == "${{ steps.immutable-release-source.outputs.sha }}"
    abort("package verifier checkout repository drifted") unless
      checkout.fetch("with").fetch("repository") == "tinyland-inc/ci-templates"

    major_run = release_jobs.fetch("move-floating-major").fetch("steps").find { |step|
      step["name"] == "Move floating major after published verification"
    }.fetch("run")
    explicit_lease = "--force-with-lease=\"refs/tags/$MAJOR_TAG:$current_major_ref\""
    abort("floating-major update lacks an explicit remote tag lease") unless major_run.include?(explicit_lease)
    abort("floating-major update trusts annotation text without exact-tag proof") unless
      major_run.include?("references missing exact tag $current_version") &&
      major_run.include?("$current_version peels to $current_version_source")
  ' "$release_file" "$package_file"
}

run_event() {
  env \
    EVENT_NAME="$1" \
    EVENT_ACTION="$2" \
    REF_TYPE="$3" \
    REF_NAME="$4" \
    RELEASE_TAG="$5" \
    bash -c "$event_guard"
}

echo "== workflow privilege and concurrency policy =="
expect_status 0 "verifier permissions, durable queue, reviewed trees, and explicit leases are exact" \
  check_workflow_policy

stale_release="$tmp/stale-release.yml"
ruby -e '
  path, output = ARGV
  text = File.read(path)
  old = "uses: ./.github/actions/immutable-release-verify"
  replacement = "uses: tinyland-inc/ci-templates/.github/actions/immutable-release-verify@6ce6ad1b6b9d2a3f40c3c05a28fd50fbaed894a3"
  abort("local verifier call missing") unless text.sub!(old, replacement)
  File.write(output, text)
' "$release_workflow" "$stale_release"
expect_status 1 "stale pinned verifier action tree is rejected" \
  check_workflow_policy "$stale_release" "$package_workflow"

stale_package="$tmp/stale-package.yml"
# The mutation targets a literal GitHub expression.
# shellcheck disable=SC2016
ruby -e '
  path, output = ARGV
  text = File.read(path)
  old = "ref: ${{ steps.immutable-release-source.outputs.sha }}"
  replacement = "ref: 6ce6ad1b6b9d2a3f40c3c05a28fd50fbaed894a3"
  abort("resolved verifier checkout ref missing") unless text.sub!(old, replacement)
  File.write(output, text)
' "$package_workflow" "$stale_package"
expect_status 1 "stale checked-out verifier action tree is rejected" \
  check_workflow_policy "$release_workflow" "$stale_package"

echo "== immutable publication event matrix =="
expect_status 0 "release:published with matching tag is accepted" \
  run_event release published tag v1.2.3 v1.2.3
expect_status 1 "tag push is rejected" \
  run_event push "" tag v1.2.3 ""
expect_status 1 "manual branch publication is rejected" \
  run_event workflow_dispatch "" branch main ""
expect_status 1 "release/ref tag mismatch is rejected" \
  run_event release published tag v1.2.3 v1.2.4

mkdir -p "$tmp/source-bin"
cat >"$tmp/source-bin/gh" <<'MOCK_RUN_API'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "api" ]]
cat "${MOCK_RUN_JSON:?}"
MOCK_RUN_API
chmod +x "$tmp/source-bin/gh"

run_source_step() {
  local run_json="$1"
  local output="$tmp/source-output"
  rm -f "$output"
  env \
    PATH="$tmp/source-bin:$PATH" \
    GH_TOKEN=test-token \
    RUN_REPOSITORY=octo/package \
    RUN_ID=123 \
    EXPECTED_WORKFLOW=tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml \
    MOCK_RUN_JSON="$run_json" \
    GITHUB_OUTPUT="$output" \
    bash -c "$source_step"
}

cat >"$tmp/reviewed-run.json" <<'JSON'
{
  "referenced_workflows": [
    {
      "path": "tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v2.12.0",
      "sha": "1111111111111111111111111111111111111111",
      "ref": "refs/tags/v2.12.0"
    }
  ]
}
JSON
cat >"$tmp/missing-run.json" <<'JSON'
{"referenced_workflows": []}
JSON

echo "== reviewed verifier source resolution =="
expect_status 0 "run metadata resolves the reviewed reusable-workflow tree" \
  run_source_step "$tmp/reviewed-run.json"
grep -qx 'sha=1111111111111111111111111111111111111111' "$tmp/source-output"
expect_status 1 "missing reviewed reusable-workflow tree fails closed" \
  run_source_step "$tmp/missing-run.json"

git init --bare -q "$tmp/remote.git"
git init -q "$tmp/work"
git -C "$tmp/work" config user.name test
git -C "$tmp/work" config user.email test@example.invalid
git -C "$tmp/work" config core.hooksPath /dev/null
git -C "$tmp/work" config commit.gpgSign false
git -C "$tmp/work" config tag.gpgSign false
printf 'base\n' >"$tmp/work/state"
git -C "$tmp/work" add state
git -C "$tmp/work" commit -q -m base
base_sha="$(git -C "$tmp/work" rev-parse HEAD)"
printf 'release\n' >>"$tmp/work/state"
git -C "$tmp/work" commit -qam release
release_sha="$(git -C "$tmp/work" rev-parse HEAD)"
git -C "$tmp/work" remote add origin "$tmp/remote.git"
git -C "$tmp/work" push -q origin HEAD:refs/heads/test-main

run_plan_step() {
  local event_name="$1"
  local requested_version="$2"
  local source_sha="$3"
  local output="$tmp/plan-output"
  rm -f "$output"
  (
    cd "$tmp/work"
    env \
      EVENT_NAME="$event_name" \
      REQUESTED_VERSION="$requested_version" \
      SOURCE_SHA="$source_sha" \
      GITHUB_OUTPUT="$output" \
      bash -c "$plan_step"
  )
}

echo "== manual fallback planning =="
expect_status 0 "manual fallback dispatch selects an exact version and source" \
  run_plan_step workflow_dispatch v1.2.3 "$release_sha"
grep -qx 'version=v1.2.3' "$tmp/plan-output"
grep -qx 'major=v1' "$tmp/plan-output"
grep -qx "source_sha=$release_sha" "$tmp/plan-output"
grep -qx 'is_release=true' "$tmp/plan-output"
expect_status 1 "manual fallback rejects a non-SemVer version" \
  run_plan_step workflow_dispatch latest "$release_sha"

run_version_step() {
  (
    cd "$tmp/work"
    env VERSION="$1" EXPECTED_SOURCE_SHA="$2" bash -c "$version_step"
  )
}

echo "== exact version tag retry and conflict paths =="
expect_status 0 "first attempt creates exact version tag" \
  run_version_step v1.2.3 "$release_sha"
expect_status 0 "retry reuses exact version tag" \
  run_version_step v1.2.3 "$release_sha"
[[ "$(git --git-dir="$tmp/remote.git" rev-list -n 1 v1.2.3)" == "$release_sha" ]]

git -C "$tmp/work" tag -a v9.9.9 "$base_sha" -m v9.9.9
git -C "$tmp/work" push -q origin refs/tags/v9.9.9
expect_status 1 "conflicting existing version tag fails closed" \
  run_version_step v9.9.9 "$release_sha"

mkdir -p "$tmp/bin" "$tmp/release-state" "$tmp/runner-temp"
cat >"$tmp/bin/gh" <<'MOCK_GH'
#!/usr/bin/env bash
set -euo pipefail
state_dir="${MOCK_RELEASE_STATE:?}"
if [[ "$1" == "release" && "$2" == "view" ]]; then
  [[ -f "$state_dir/release.json" ]] || exit 1
  cat "$state_dir/release.json"
  exit 0
fi
if [[ "$1" == "release" && "$2" == "create" ]]; then
  count=0
  [[ ! -f "$state_dir/create-count" ]] || count="$(<"$state_dir/create-count")"
  printf '%s\n' "$((count + 1))" >"$state_dir/create-count"
  printf '{"tagName":"%s","isDraft":false,"isPrerelease":false}\n' "$3" >"$state_dir/release.json"
  exit 0
fi
exit 97
MOCK_GH
chmod +x "$tmp/bin/gh"
cat >"$tmp/work/CHANGELOG.md" <<'CHANGELOG'
## [Unreleased]

## [1.2.3]

- Release notes.
CHANGELOG

run_release_step() {
  (
    cd "$tmp/work"
    env \
      PATH="$tmp/bin:$PATH" \
      MOCK_RELEASE_STATE="$tmp/release-state" \
      RUNNER_TEMP="$tmp/runner-temp" \
      VERSION=v1.2.3 \
      EXPECTED_SOURCE_SHA="$release_sha" \
      bash -c "$release_step"
  )
}

echo "== published Release retry paths =="
expect_status 0 "first attempt creates published Release" run_release_step
expect_status 0 "retry reuses published Release" run_release_step
[[ "$(<"$tmp/release-state/create-count")" == "1" ]]
printf '{"tagName":"v1.2.3","isDraft":true,"isPrerelease":false}\n' >"$tmp/release-state/release.json"
expect_status 1 "draft recovery state fails closed" run_release_step
printf '{"tagName":"v1.2.3","isDraft":false,"isPrerelease":false}\n' >"$tmp/release-state/release.json"

run_major_step() {
  (
    cd "$tmp/work"
    env VERSION="$1" MAJOR_TAG=v1 EXPECTED_SOURCE_SHA="$2" bash -c "$major_step"
  )
}

echo "== floating-major commit boundary =="
expect_status 0 "verified release advances floating major" \
  run_major_step v1.2.3 "$release_sha"
major_ref_before="$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)"
expect_status 0 "retry leaves already-correct floating major unchanged" \
  run_major_step v1.2.3 "$release_sha"
major_ref_after="$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)"
[[ "$major_ref_before" == "$major_ref_after" ]]

expect_status 1 "conflicting version tag cannot move floating major" \
  run_major_step v9.9.9 "$release_sha"
[[ "$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)" == "$major_ref_before" ]]

printf 'newer release\n' >>"$tmp/work/state"
git -C "$tmp/work" commit -qam newer-release
newer_release_sha="$(git -C "$tmp/work" rev-parse HEAD)"
expect_status 0 "newer exact version tag is created" \
  run_version_step v1.3.0 "$newer_release_sha"
expect_status 0 "newer verified release advances floating major" \
  run_major_step v1.3.0 "$newer_release_sha"
newer_major_ref="$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)"
expect_status 1 "older release rerun cannot roll floating major backward" \
  run_major_step v1.2.3 "$release_sha"
[[ "$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)" == "$newer_major_ref" ]]
[[ "$(git --git-dir="$tmp/remote.git" rev-list -n 1 v1)" == "$newer_release_sha" ]]

set_remote_major() {
  local tracked_version="$1"
  local source_sha="$2"
  git -C "$tmp/work" tag -f -a v1 "$source_sha" -m "track $tracked_version"
  git -C "$tmp/work" push -q --force origin refs/tags/v1
}

set_remote_major v1.99.0 "$newer_release_sha"
forged_major_ref="$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)"
expect_status 1 "forged annotation cannot name a missing exact tag" \
  run_major_step v1.3.0 "$newer_release_sha"
[[ "$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)" == "$forged_major_ref" ]]

git -C "$tmp/work" tag -a v1.99.0 "$base_sha" -m v1.99.0
git -C "$tmp/work" push -q origin refs/tags/v1.99.0
expect_status 1 "forged annotation cannot borrow a mismatched exact tag" \
  run_major_step v1.3.0 "$newer_release_sha"
[[ "$(git --git-dir="$tmp/remote.git" rev-parse refs/tags/v1)" == "$forged_major_ref" ]]

set_remote_major v1.3.0 "$newer_release_sha"
expect_status 1 "manual fallback cannot move the floating major backward" \
  run_major_step v1.2.3 "$release_sha"
[[ "$(git --git-dir="$tmp/remote.git" rev-list -n 1 v1)" == "$newer_release_sha" ]]

echo
echo "immutable-release workflow self-test: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
