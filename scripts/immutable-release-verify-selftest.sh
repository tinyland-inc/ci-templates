#!/usr/bin/env bash

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
verifier="${here}/immutable-release-verify.sh"

if [[ ! -x "$verifier" ]]; then
  echo "ERROR: verifier script not found/executable at $verifier" >&2
  exit 2
fi

real_jq="$(command -v jq)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home"

cat >"$tmp/bin/gh" <<'MOCK_GH'
#!/usr/bin/env bash
set -euo pipefail

[[ -z "${IMMUTABLE_RELEASE_ADMIN_TOKEN:-}" ]] || exit 98
[[ -z "${IMMUTABLE_RELEASE_CONTENTS_TOKEN:-}" ]] || exit 99

sha1="1111111111111111111111111111111111111111"
sha1_other="2222222222222222222222222222222222222222"
sha256="1111111111111111111111111111111111111111111111111111111111111111"
tag_object_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
scenario="${MOCK_SCENARIO:-published}"
state_dir="${MOCK_STATE_DIR:?}"

increment() {
  local name="$1"
  local path="${state_dir}/${name}"
  local value=0
  [[ ! -f "$path" ]] || value="$(<"$path")"
  value=$((value + 1))
  printf '%s\n' "$value" >"$path"
  printf '%s' "$value"
}

if [[ "$1" == "api" ]]; then
  [[ " $* " == *" X-GitHub-Api-Version: 2026-03-10 "* ]] || exit 90
  endpoint="${*: -1}"
  if [[ "$endpoint" == "repos/octo/example/immutable-releases" ]]; then
    [[ "${GH_TOKEN:-}" == "admin-token" ]] || exit 91
    [[ "$(increment admin-calls)" == "1" ]] || exit 89
    case "$scenario" in
      setting-api-failure) exit 1 ;;
      setting-disabled) printf '{"enabled":false,"enforced_by_owner":false}\n' ;;
      *) printf '{"enabled":true,"enforced_by_owner":false}\n' ;;
    esac
    exit 0
  fi

  [[ "${GH_TOKEN:-}" == "contents-token" ]] || exit 92
  if [[ "$endpoint" == "repos/octo/example/git/ref/tags/v1.2.3" ]]; then
    case "$scenario" in
      lightweight) printf '{"object":{"type":"commit","sha":"%s"}}\n' "$sha1" ;;
      sha256) printf '{"object":{"type":"commit","sha":"%s"}}\n' "$sha256" ;;
      *) printf '{"object":{"type":"tag","sha":"%s"}}\n' "$tag_object_sha" ;;
    esac
    exit 0
  fi
  if [[ "$endpoint" == "repos/octo/example/git/tags/$tag_object_sha" ]]; then
    if [[ "$scenario" == "tag-mismatch" ]]; then
      printf '{"object":{"type":"commit","sha":"%s"}}\n' "$sha1_other"
    else
      printf '{"object":{"type":"commit","sha":"%s"}}\n' "$sha1"
    fi
    exit 0
  fi
  if [[ "$endpoint" == "repos/octo/example/releases/tags/v1.2.3" ]]; then
    release_call="$(increment release-calls)"
    if [[ "$scenario" == "release-transient" && "$release_call" -lt 3 ]]; then
      exit 1
    fi
    case "$scenario" in
      release-mutable)
        printf '{"tag_name":"v1.2.3","draft":false,"published_at":"2026-07-11T00:00:00Z","immutable":false}\n'
        ;;
      release-tag-mismatch)
        printf '{"tag_name":"v9.9.9","draft":false,"published_at":"2026-07-11T00:00:00Z","immutable":true}\n'
        ;;
      *)
        printf '{"tag_name":"v1.2.3","draft":false,"published_at":"2026-07-11T00:00:00Z","immutable":true}\n'
        ;;
    esac
    exit 0
  fi
  exit 94
fi

if [[ "$1" == "release" && "$2" == "verify" && "${3:-}" == "--help" ]]; then
  [[ "$scenario" != "missing-gh-release-verify" ]]
  exit
fi

if [[ "$1" == "release" && "$2" == "verify" ]]; then
  [[ "${GH_TOKEN:-}" == "contents-token" ]] || exit 96
  attestation_call="$(increment attestation-calls)"
  if [[ "$scenario" == "attestation-unavailable" ]]; then
    exit 1
  fi
  if [[ "$scenario" == "attestation-transient" && "$attestation_call" -lt 3 ]]; then
    exit 1
  fi

  attested_repo="octo/example"
  attested_tag="v1.2.3"
  attested_sha="$sha1"
  digest_algorithm="sha1"
  case "$scenario" in
    attestation-repo-mismatch) attested_repo="octo/other" ;;
    attestation-tag-mismatch) attested_tag="v9.9.9" ;;
    attestation-digest-mismatch) attested_sha="$sha1_other" ;;
    sha256)
      attested_sha="$sha256"
      digest_algorithm="sha256"
      ;;
  esac
  purl="pkg:github/${attested_repo}@${attested_tag}"
  cat <<JSON
{"verificationResult":{"statement":{"predicateType":"https://in-toto.io/attestation/release/v0.2","predicate":{"repository":"${attested_repo}","tag":"${attested_tag}","purl":"${purl}"},"subject":[{"uri":"${purl}","digest":{"${digest_algorithm}":"${attested_sha}"}}]}}}
JSON
  exit 0
fi

exit 97
MOCK_GH

cat >"$tmp/bin/jq" <<'MOCK_JQ'
#!/usr/bin/env bash
set -euo pipefail
[[ -z "${IMMUTABLE_RELEASE_ADMIN_TOKEN:-}" ]] || exit 98
[[ -z "${IMMUTABLE_RELEASE_CONTENTS_TOKEN:-}" ]] || exit 99
exec "${REAL_JQ:?}" "$@"
MOCK_JQ

cat >"$tmp/bin/git" <<'MOCK_GIT'
#!/usr/bin/env bash
set -euo pipefail
[[ -z "${IMMUTABLE_RELEASE_ADMIN_TOKEN:-}" ]] || exit 98
[[ -z "${IMMUTABLE_RELEASE_CONTENTS_TOKEN:-}" ]] || exit 99
[[ "$1" == "check-ref-format" ]]
MOCK_GIT

cat >"$tmp/bin/sleep" <<'MOCK_SLEEP'
#!/usr/bin/env bash
set -euo pipefail
[[ -z "${IMMUTABLE_RELEASE_ADMIN_TOKEN:-}" ]] || exit 98
[[ -z "${IMMUTABLE_RELEASE_CONTENTS_TOKEN:-}" ]] || exit 99
printf '%s\n' "$1" >>"${MOCK_STATE_DIR:?}/sleeps"
MOCK_SLEEP
chmod +x "$tmp/bin/gh" "$tmp/bin/jq" "$tmp/bin/git" "$tmp/bin/sleep"

pass=0
fail=0

run_case() {
  local expected_exit="$1"
  local description="$2"
  local mode="$3"
  local scenario="$4"
  local expected_output="$5"
  local expected_sha="1111111111111111111111111111111111111111"
  local state_dir="${tmp}/state-${pass}-${fail}-${RANDOM}"
  local actual output
  local -a environment

  mkdir -p "$state_dir"
  [[ "$scenario" != "sha256" ]] || expected_sha="1111111111111111111111111111111111111111111111111111111111111111"
  environment=(
    "PATH=$tmp/bin:$PATH"
    "HOME=$tmp/home"
    "REAL_JQ=$real_jq"
    "MOCK_SCENARIO=$scenario"
    "MOCK_STATE_DIR=$state_dir"
    "IMMUTABLE_RELEASE_MODE=$mode"
    "IMMUTABLE_RELEASE_REPOSITORY=octo/example"
    "IMMUTABLE_RELEASE_VERIFY_ATTEMPTS=3"
    "IMMUTABLE_RELEASE_VERIFY_RETRY_SECONDS=0"
  )

  if [[ "$mode" == "settings" ]]; then
    [[ "$scenario" == "missing-admin-token" ]] || environment+=("IMMUTABLE_RELEASE_ADMIN_TOKEN=admin-token")
    [[ "$scenario" != "unexpected-contents-token" ]] || environment+=("IMMUTABLE_RELEASE_CONTENTS_TOKEN=contents-token")
  else
    environment+=(
      "IMMUTABLE_RELEASE_TAG=v1.2.3"
      "IMMUTABLE_RELEASE_EXPECTED_SOURCE_SHA=$expected_sha"
      "IMMUTABLE_RELEASE_CONTENTS_TOKEN=contents-token"
    )
    [[ "$scenario" != "unexpected-admin-token" ]] || environment+=("IMMUTABLE_RELEASE_ADMIN_TOKEN=admin-token")
  fi

  set +e
  output="$(env -i "${environment[@]}" bash "$verifier" 2>&1)"
  actual=$?
  set -e

  if [[ "$actual" -eq "$expected_exit" ]] && grep -Fq "$expected_output" <<<"$output"; then
    pass=$((pass + 1))
    printf 'ok   [exit %d] %s\n' "$actual" "$description"
  else
    fail=$((fail + 1))
    printf 'FAIL [exit %d, want %d] %s\n' "$actual" "$expected_exit" "$description"
    printf '       output: %s\n' "$(tail -1 <<<"$output")"
  fi
}

echo "== settings/token-boundary paths =="
run_case 0 "settings performs one isolated Administration read" settings enabled \
  "immutable releases enabled"
run_case 1 "settings requires runtime App token" settings missing-admin-token \
  "settings mode requires an Administration-read GitHub App token"
run_case 1 "settings rejects a Contents token" settings unexpected-contents-token \
  "settings mode does not accept a Contents token"
run_case 1 "immutable-release setting disabled" settings setting-disabled \
  "immutable releases are not enabled"
run_case 1 "immutable-release setting API failure" settings setting-api-failure \
  "cannot confirm immutable releases"

echo "== published happy and retry paths =="
run_case 0 "published accepts a lightweight exact tag" published lightweight \
  "release attestation binding verified"
run_case 0 "published peels an annotated exact tag" published published \
  "release attestation binding verified"
run_case 0 "published supports SHA-256 repositories" published sha256 \
  "release attestation binding verified"
run_case 0 "published retries delayed Release visibility" published release-transient \
  "release attestation binding verified"
run_case 0 "published retries delayed attestation readiness" published attestation-transient \
  "release attestation binding verified"

echo "== published fail-closed paths =="
run_case 1 "published rejects Administration token leakage" published unexpected-admin-token \
  "published mode does not accept an Administration token"
run_case 1 "peeled tag differs from expected source" published tag-mismatch \
  "expected 1111111111111111111111111111111111111111"
run_case 1 "mutable Release exhausts bounded retries" published release-mutable \
  "did not become immutable and attestable after 3 attempt(s)"
run_case 1 "release tag does not match exact tag" published release-tag-mismatch \
  "draft, or tag-mismatched"
run_case 1 "GitHub CLI lacks release attestation verification" published missing-gh-release-verify \
  "does not support cryptographic release-attestation verification"
run_case 1 "unavailable attestation exhausts bounded retries" published attestation-unavailable \
  "did not become immutable and attestable after 3 attempt(s)"
run_case 1 "attestation repository binding differs" published attestation-repo-mismatch \
  "does not bind octo/example@v1.2.3"
run_case 1 "attestation tag binding differs" published attestation-tag-mismatch \
  "does not bind octo/example@v1.2.3"
run_case 1 "attestation source digest differs" published attestation-digest-mismatch \
  "does not bind octo/example@v1.2.3"

echo
echo "immutable-release verifier self-test: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
