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
  ruby -ryaml -e '
    release = YAML.load_file(ARGV.fetch(0))
    package = YAML.load_file(ARGV.fetch(1))

    concurrency = release.fetch("concurrency")
    abort("release concurrency must retain the supported maximum pending queue") unless concurrency["queue"] == "max"
    abort("release concurrency must not cancel an in-progress transaction") if concurrency["cancel-in-progress"] == true

    release_jobs = release.fetch("jobs")
    verify_permissions = release_jobs.fetch("verify-published-release").fetch("permissions")
    abort("release verifier permissions drifted") unless verify_permissions == {
      "attestations" => "read",
      "contents" => "read",
    }

    package_permissions = package.fetch("jobs").fetch("resolve-runner").fetch("permissions")
    abort("package verifier permissions drifted") unless package_permissions == {
      "attestations" => "read",
      "contents" => "read",
    }

    expected_checkout = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    %w[publish-version-release move-floating-major].each do |job_name|
      checkout = release_jobs.fetch(job_name).fetch("steps").find { |step| step.key?("uses") }
      abort("#{job_name} checkout is not pinned to the reviewed SHA") unless checkout["uses"] == expected_checkout
    end
  ' "$release_workflow" "$package_workflow"
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
expect_status 0 "verifier permissions, durable queue, and write-job pins are exact" \
  check_workflow_policy

echo "== immutable publication event matrix =="
expect_status 0 "release:published with matching tag is accepted" \
  run_event release published tag v1.2.3 v1.2.3
expect_status 1 "tag push is rejected" \
  run_event push "" tag v1.2.3 ""
expect_status 1 "manual branch publication is rejected" \
  run_event workflow_dispatch "" branch main ""
expect_status 1 "release/ref tag mismatch is rejected" \
  run_event release published tag v1.2.3 v1.2.4

git init --bare -q "$tmp/remote.git"
git init -q "$tmp/work"
git -C "$tmp/work" config user.name test
git -C "$tmp/work" config user.email test@example.invalid
git -C "$tmp/work" config core.hooksPath /dev/null
printf 'base\n' >"$tmp/work/state"
git -C "$tmp/work" add state
git -C "$tmp/work" commit -q -m base
base_sha="$(git -C "$tmp/work" rev-parse HEAD)"
printf 'release\n' >>"$tmp/work/state"
git -C "$tmp/work" commit -qam release
release_sha="$(git -C "$tmp/work" rev-parse HEAD)"
git -C "$tmp/work" remote add origin "$tmp/remote.git"
git -C "$tmp/work" push -q origin HEAD:refs/heads/test-main

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

echo
echo "immutable-release workflow self-test: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
