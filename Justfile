# ci-templates task runner
# Use `just <recipe>` locally and `nix develop --command just <recipe>` in CI.

set shell := ["bash", "-euo", "pipefail", "-c"]

root := justfile_directory()

_default:
    @just --list --unsorted

# Run all repository-local validation.
check: yaml-parse json-parse repo-manifest-validate internal-refs-check endpoint-free-check secrets-scan-dir
    @echo "ci-templates checks passed."

# Parse all GitHub workflow/action YAML with Ruby's stdlib YAML parser.
yaml-parse:
    cd {{ root }} && ruby -e 'require "yaml"; Dir[".github/**/*.{yml,yaml}"].sort.each { |f| YAML.load_file(f); puts "yaml ok: #{f}" }'

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

# Ensure the v2 Flywheel bazelrc fragment has no baked endpoints or upload authority.
endpoint-free-check:
    cd {{ root }} && ! grep -Eq -- '--remote_cache=|--remote_executor=|--remote_upload_local_results=true|grpc://bazel-cache|grpc://gf-reapi-cell' bazelrc/flywheel.bazelrc
    @echo "flywheel.bazelrc endpoint-free"

# Scan current files for secrets.
secrets-scan-dir:
    cd {{ root }} && gitleaks dir --config .gitleaks.toml --redact --verbose .

# Scan git history for secrets.
secrets-scan:
    cd {{ root }} && gitleaks git --config .gitleaks.toml --redact --verbose .
