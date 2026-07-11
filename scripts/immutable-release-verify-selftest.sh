#!/usr/bin/env bash

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
verifier="${here}/immutable-release-verify.sh"

if [[ ! -x "$verifier" ]]; then
  echo "ERROR: verifier script not found/executable at $verifier" >&2
  exit 2
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/home"

cat >"$tmp/bin/gh" <<'MOCK_GH'
#!/usr/bin/env bash
set -euo pipefail

sha1="1111111111111111111111111111111111111111"
sha1_other="2222222222222222222222222222222222222222"
sha256="1111111111111111111111111111111111111111111111111111111111111111"
tag_object_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
scenario="${MOCK_SCENARIO:-published}"
mode="${MOCK_MODE:-published}"

if [[ "$1" == "api" ]]; then
  [[ " $* " == *" X-GitHub-Api-Version: 2026-03-10 "* ]] || exit 90
  endpoint="${*: -1}"
  if [[ "$endpoint" == "repos/octo/example/immutable-releases" ]]; then
    [[ "${GH_TOKEN:-}" == "admin-token" ]] || exit 91
    if [[ "$scenario" == "setting-api-failure" ]]; then
      exit 1
    elif [[ "$scenario" == "setting-disabled" ]]; then
      printf '{"enabled":false,"enforced_by_owner":false}\n'
    else
      printf '{"enabled":true,"enforced_by_owner":false}\n'
    fi
    exit 0
  fi

  [[ "${GH_TOKEN:-}" == "contents-token" ]] || exit 92
  if [[ "$endpoint" == "repos/octo/example/git/ref/tags/v1.2.3" ]]; then
    if [[ "$scenario" == "lightweight" ]]; then
      printf '{"object":{"type":"commit","sha":"%s"}}\n' "$sha1"
    elif [[ "$scenario" == "sha256" ]]; then
      printf '{"object":{"type":"commit","sha":"%s"}}\n' "$sha256"
    else
      printf '{"object":{"type":"tag","sha":"%s"}}\n' "$tag_object_sha"
    fi
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
    [[ "$mode" == "published" ]] || exit 93
    if [[ "$scenario" == "release-mutable" ]]; then
      printf '{"tag_name":"v1.2.3","draft":false,"published_at":"2026-07-11T00:00:00Z","immutable":false,"target_commitish":"%s"}\n' "$sha1"
    elif [[ "$scenario" == "release-tag-mismatch" ]]; then
      printf '{"tag_name":"v9.9.9","draft":false,"published_at":"2026-07-11T00:00:00Z","immutable":true,"target_commitish":"%s"}\n' "$sha1"
    else
      printf '{"tag_name":"v1.2.3","draft":false,"published_at":"2026-07-11T00:00:00Z","immutable":true,"target_commitish":"%s"}\n' "$sha1_other"
    fi
    exit 0
  fi
  exit 94
fi

if [[ "$1" == "release" && "$2" == "verify" && "${3:-}" == "--help" ]]; then
  [[ "$scenario" != "missing-gh-release-verify" ]]
  exit
fi

if [[ "$1" == "release" && "$2" == "verify" ]]; then
  [[ "$mode" == "published" ]] || exit 95
  [[ "${GH_TOKEN:-}" == "contents-token" ]] || exit 96
  [[ "$scenario" != "attestation-unavailable" ]] || exit 1

  attested_repo="octo/example"
  attested_tag="v1.2.3"
  attested_sha="$sha1"
  digest_algorithm="sha1"
  if [[ "$scenario" == "attestation-repo-mismatch" ]]; then
    attested_repo="octo/other"
  elif [[ "$scenario" == "attestation-tag-mismatch" ]]; then
    attested_tag="v9.9.9"
  elif [[ "$scenario" == "attestation-digest-mismatch" ]]; then
    attested_sha="$sha1_other"
  elif [[ "$scenario" == "sha256" ]]; then
    attested_sha="$sha256"
    digest_algorithm="sha256"
  fi
  purl="pkg:github/${attested_repo}@${attested_tag}"
  cat <<JSON
{"attestation":{"bundle":{}},"verificationResult":{"statement":{"predicateType":"https://in-toto.io/attestation/release/v0.2","predicate":{"repository":"${attested_repo}","tag":"${attested_tag}","purl":"${purl}"},"subject":[{"uri":"${purl}","digest":{"${digest_algorithm}":"${attested_sha}"}}]}}}
JSON
  exit 0
fi

exit 97
MOCK_GH
chmod +x "$tmp/bin/gh"

pass=0
fail=0

run_case() {
  local expected_exit="$1"
  local description="$2"
  local mode="$3"
  local scenario="$4"
  local expected_output="$5"
  local expected_sha="1111111111111111111111111111111111111111"
  local actual output
  local -a environment

  if [[ "$scenario" == "sha256" ]]; then
    expected_sha="1111111111111111111111111111111111111111111111111111111111111111"
  fi

  environment=(
    "PATH=$tmp/bin:$PATH"
    "HOME=$tmp/home"
    "MOCK_MODE=$mode"
    "MOCK_SCENARIO=$scenario"
    "IMMUTABLE_RELEASE_MODE=$mode"
    "IMMUTABLE_RELEASE_REPOSITORY=octo/example"
    "IMMUTABLE_RELEASE_TAG=v1.2.3"
    "IMMUTABLE_RELEASE_EXPECTED_SOURCE_SHA=$expected_sha"
    "IMMUTABLE_RELEASE_CONTENTS_TOKEN=contents-token"
  )
  if [[ "$scenario" != "missing-admin-token" ]]; then
    environment+=("IMMUTABLE_RELEASE_ADMIN_TOKEN=admin-token")
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

echo "== happy paths =="
run_case 0 "prepublish accepts a lightweight exact tag" prepublish lightweight \
  "exact tag binding verified"
run_case 0 "prepublish peels an annotated exact tag" prepublish annotated \
  "exact tag binding verified"
run_case 0 "published verifies immutable release and attestation" published published \
  "release attestation binding verified"
run_case 0 "published supports SHA-256 repositories" published sha256 \
  "release attestation binding verified"

echo "== fail-closed setting and tag paths =="
run_case 1 "missing Administration-read token" prepublish missing-admin-token \
  "requires an Administration-read GitHub App token"
run_case 1 "immutable-release setting disabled" prepublish setting-disabled \
  "immutable releases are not enabled"
run_case 1 "immutable-release setting API failure" prepublish setting-api-failure \
  "cannot confirm immutable releases"
run_case 1 "peeled tag differs from expected source" prepublish tag-mismatch \
  "expected 1111111111111111111111111111111111111111"

echo "== fail-closed published paths =="
run_case 1 "release is mutable" published release-mutable \
  "not immutable"
run_case 1 "release tag does not match exact tag" published release-tag-mismatch \
  "tag-mismatched"
run_case 1 "GitHub CLI lacks release attestation verification" published missing-gh-release-verify \
  "does not support cryptographic release-attestation verification"
run_case 1 "release attestation is unavailable" published attestation-unavailable \
  "attestation is unavailable"
run_case 1 "attestation repository binding differs" published attestation-repo-mismatch \
  "does not bind octo/example@v1.2.3"
run_case 1 "attestation tag binding differs" published attestation-tag-mismatch \
  "does not bind octo/example@v1.2.3"
run_case 1 "attestation source digest differs" published attestation-digest-mismatch \
  "does not bind octo/example@v1.2.3"

echo
echo "immutable-release verifier self-test: $pass passed, $fail failed"
if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
