# ci-templates task runner
# Use `just <recipe>` locally and `nix develop --command just <recipe>` in CI.

set shell := ["bash", "-euo", "pipefail", "-c"]

root := justfile_directory()

_default:
    @just --list --unsorted

# Run all repository-local validation.
check: yaml-parse json-parse repo-manifest-validate manifest-validate-selftest internal-refs-check js-bazel-runner-contract-check immutable-release-contract-check immutable-release-selftest flywheel-reapi-proof-contract-check endpoint-free-check ci-cached-endpoint-free-check cache-backed-optin-contract-check cache-contract-selftest secrets-scan-dir lint-runs-on-selftest lint-runs-on-check
    @echo "ci-templates checks passed."

# Parse all GitHub workflow/action YAML with Ruby's stdlib YAML parser.
yaml-parse:
    cd {{ root }} && ruby -e 'require "yaml"; Dir[".github/**/*.{yml,yaml}"].sort.each { |f| YAML.load_file(f); puts "yaml ok: #{f}" }'

# Self-test the runs-on guard against its taxonomy oracle (parity with
# GloriousFlywheel validate-arc-runner-taxonomy.py::label_errors()).
lint-runs-on-selftest:
    cd {{ root }} && ruby scripts/lint-runs-on.rb --self-test

# Guard ci-templates' OWN workflow runs-on labels (dogfood the action).
lint-runs-on-check:
    cd {{ root }} && ruby scripts/lint-runs-on.rb --root {{ root }}

# Parse all vendored JSON schemas.
json-parse:
    cd {{ root }} && for f in schemas/*.json tinyland.repo.json; do jq empty "$f"; echo "json ok: $f"; done

# Validate tinyland.repo.json against the vendored Tinyland repo manifest schema.
repo-manifest-validate:
    cd {{ root }} && if python3 -c 'import jsonschema' >/dev/null 2>&1; then \
      validator=(python3); \
    elif command -v nix >/dev/null 2>&1; then \
      validator=(nix develop --command python3); \
    else \
      echo "python jsonschema unavailable and nix missing" >&2; exit 2; \
    fi; \
    "${validator[@]}" scripts/validate-ci-templates.py manifest

# Ensure internal ci-templates action refs resolve to checked-in sibling actions.
internal-refs-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py internal-refs

# Ensure js-bazel-package keeps runner-mode semantics aligned with GloriousFlywheel.
js-bazel-runner-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py js-bazel-runner-contract

# Guard the opt-in immutable-release gate, token boundary, and release ordering.
immutable-release-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py immutable-release-contract

# Prove prepublish/published happy paths and fail-closed release checks without
# reading live settings, tags, releases, attestations, or credentials.
immutable-release-selftest:
    cd {{ root }} && bash scripts/immutable-release-verify-selftest.sh

# Ensure flywheel-reapi-proof keeps child-run correlation request-id based.
flywheel-reapi-proof-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py flywheel-reapi-proof-contract

# Ensure the v2 Flywheel bazelrc fragment has no baked endpoints or upload authority.
endpoint-free-check:
    cd {{ root }} && ! grep -Eq -- '--remote_cache=|--remote_executor=|--remote_upload_local_results=true|grpc://bazel-cache|grpc://gf-reapi-cell' bazelrc/flywheel.bazelrc
    @echo "flywheel.bazelrc endpoint-free"

# Ensure the ci-cached bazelrc fragment has no baked endpoints or upload authority.
# `--remote_cache=` with an empty value (the no-remote-cache disable knob) is the
# only permitted occurrence; any non-empty endpoint or executor is rejected.
ci-cached-endpoint-free-check:
    cd {{ root }} && ! grep -Eq -- '--remote_cache=[^[:space:]]|--remote_executor=|--remote_upload_local_results=true|grpc://bazel-cache|grpc://gf-reapi-cell|grpcs?://[a-z0-9.-]+:[0-9]' bazelrc/ci-cached.bazelrc
    @echo "ci-cached.bazelrc endpoint-free"

# Ensure the cache-backed opt-in stays opt-in/default-off and cache-first
# (no remote executor wired in the workflow's cache-backed path).
cache-backed-optin-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py cache-backed-optin-contract

# Prove the cache-attachment contract's fail-closed paths actually fail closed
# (declared-vs-actual mismatch, hosted/repo-label fallback, executor-backed
# without the required set, plus the pre-existing endpoint guards). TIN-2109.
cache-contract-selftest:
    cd {{ root }} && bash scripts/cache-attachment-contract-selftest.sh

# Prove the dependency-free manifest validator accepts the real manifest and
# fails closed on an invalid one (no jsonschema/nix/network required). TIN-2109.
manifest-validate-selftest:
    cd {{ root }} && python3 scripts/manifest-schema-validate.py schemas/tinyland-repo-manifest.schema.json tinyland.repo.json
    cd {{ root }} && bad=$(mktemp) && jq '.schema_version=2' tinyland.repo.json > "$bad" && \
      if python3 scripts/manifest-schema-validate.py schemas/tinyland-repo-manifest.schema.json "$bad" 2>/dev/null; then \
        echo "FAIL: validator did not reject an invalid manifest" >&2; rm -f "$bad"; exit 1; \
      else echo "manifest validator fails closed on invalid manifest"; rm -f "$bad"; fi

# Scan current files for secrets.
secrets-scan-dir:
    cd {{ root }} && gitleaks dir --config .gitleaks.toml --redact --verbose .

# Scan git history for secrets.
secrets-scan:
    cd {{ root }} && gitleaks git --config .gitleaks.toml --redact --verbose .
