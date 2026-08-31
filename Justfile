# ci-templates task runner
# Use `just <recipe>` locally and `nix develop --command just <recipe>` in CI.

set shell := ["bash", "-euo", "pipefail", "-c"]

root := justfile_directory()

_default:
    @just --list --unsorted

# CT-01 census at this carrier: 26 registered targets; endpoint-free-check is
# target 15. actionlint remains a separate future PR-gate command so this
# executable census stays truthful while the runner-group decision is on HOLD.
# Run all repository-local validation.
check: yaml-parse json-parse vendored-schema-provenance-check repo-manifest-validate manifest-validate-selftest internal-refs-check js-bazel-runner-contract-check rust-bazel-application-contract-check flywheel-reapi-proof-contract-check restricted-workflow-contract-check runner-group-contract-selftest runner-group-contract-check repo-role-census-contract-selftest repo-role-census-contract-check endpoint-free-check ci-cached-endpoint-free-check cache-backed-optin-contract-check cache-contract-selftest secrets-scan-dir lint-runs-on-selftest lint-runs-on-check no-hosted-runners-selftest no-hosted-runners-check lanes-schema-runner-class-check gf-i09-publisher-contract-check gf-i09-publisher-contract-selftest
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

# TIN-3914 backstop: no GitHub-hosted runner label survives on ANY surface that
# can carry one into a scheduler — workflow/action YAML, the vendored JSON
# schemas that validate CONSUMER lanes.json, this repo's manifest, and the
# bazelrc fragments. `lint-runs-on.rb` verdicts `runs-on` values structurally;
# this catches a label hiding in an input default, a fromJSON fallback string,
# an env value, or a schema enum. Label-aware and case-insensitive: the grep
# this replaced failed `blacksmith-4vcpu-ubuntu-2204` while passing
# `namespace-profile-default` (same third-party fleet, opposite verdicts, purely
# because one embeds `ubuntu-2`) and let `Ubuntu-Latest` through entirely.
no-hosted-runners-check:
    cd {{ root }} && ruby scripts/no-hosted-runners.rb --root {{ root }}

# Prove the backstop's classifier on the exact cases that broke its predecessor:
# mixed case, both third-party fleets, schema consts, and comment-only prose.
no-hosted-runners-selftest:
    cd {{ root }} && ruby scripts/no-hosted-runners.rb --self-test

# TIN-3914 (semantic, not textual): prove no GitHub-hosted label is even
# REPRESENTABLE as a lanes.json runnerClass. That value is consumer data which
# lanes-load feeds into spoke-ci's `matrix.lane.runner_class`, i.e. straight
# into runs-on, so a schema that sanctions one is a hosted path no
# workflow-text linter can see. Executes every accept-arm against hostile and
# legitimate label sets, so a future arm that re-opens the hole in a new
# spelling fails even if it never writes a hosted label down.
lanes-schema-runner-class-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py lanes-schema-runner-class

# CT-01 future PR-gate contract. This deliberately chooses no runner group.
# Until validate.yml exists, it proves the 26-target/#15 census and its own
# hostile fixtures, then reports the explicit runner-selection HOLD.
actionlint-check:
    cd {{ root }} && actionlint -config-file .github/actionlint.yaml -ignore 'property "labels" is not defined' -ignore 'SC2086:info:8:38: Double quote to prevent globbing and word splitting'
    cd {{ root }} && python3 scripts/ct-01-validation-contract.py
    cd {{ root }} && python3 scripts/ct-01-validation-contract.py --self-test

# GF-I09 publisher-only workflow: structural contract plus hostile mutation oracles.
gf-i09-publisher-contract-check:
    cd {{ root }} && python3 scripts/gf-i09-publisher-contract.py

gf-i09-publisher-contract-selftest:
    cd {{ root }} && python3 scripts/gf-i09-publisher-contract.py --self-test

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

# Assert every vendored manifest schema still matches schemas/VENDORED.json.
# Hermetic by design: it compares recorded digests and does NOT reach
# site.scaffold — a network call here would make every consumer's CI depend on
# another repo being reachable. It catches a hand-edited copy, which is what a
# lock can catch offline; upstream freshness is a separate, non-blocking
# question. A `drifted` entry is reported, not failed.
vendored-schema-provenance-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py vendored-schema-provenance

# Ensure internal ci-templates action refs resolve to checked-in sibling actions.
internal-refs-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py internal-refs

# Ensure js-bazel-package keeps runner-mode semantics aligned with GloriousFlywheel.
js-bazel-runner-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py js-bazel-runner-contract

# Guard the opt-in native Rust+Bazel workflow and exercise its dependency-free
# finite-target parser. No consumer checkout or cache endpoint is required.
rust-bazel-application-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py rust-bazel-application-contract
    cd {{ root }} && python3 .github/actions/rust-bazel-contract/contract.py --self-test
    cd {{ root }} && python3 .github/actions/rust-bazel-binary-custody/custody.py --self-test

# Ensure flywheel-reapi-proof keeps child-run correlation request-id based.
flywheel-reapi-proof-contract-check:
    cd {{ root }} && python3 scripts/validate-ci-templates.py flywheel-reapi-proof-contract

# Keep restricted private-repo workflow routing group+capability bound, prove
# its full dependency closure immutable, and preserve fleet-wide legacy bytes.
restricted-workflow-contract-check:
    cd {{ root }} && ruby scripts/restricted-workflow-contract.rb

# Prove spoke-ci's optional runner_group input (TIN-3902) is default-off: with
# it unset every rendered runs-on is byte-for-byte the pinned label-only
# baseline; with it set all seven jobs render GitHub's {group, labels} mapping
# with the same labels they resolve today. TIN-3914 retired the hosted-job
# class, so the never-group-routed literal class is now empty and its rule is
# kept executable by a synthetic-baseline oracle in the self-test.
runner-group-contract-check:
    cd {{ root }} && ruby scripts/runner-group-contract.rb

# Prove that default-off checker rejects its negative oracles (unconditional
# group mapping, group leaking into a hosted job, dropped/rerouted labels).
runner-group-contract-selftest:
    cd {{ root }} && ruby scripts/runner-group-contract.rb --self-test

# Prove spoke-ci's optional allowed_repo_roles input (TIN-3815) is default-off
# and reaches EVERY census site. The bug it fixes was two independently
# hardcoded allowlists, so the primary assertion is a site census: the set of
# repo-manifest-validate invocations is pinned, and each must route through the
# input. Unset renders the pre-TIN-3815 literal byte-for-byte; set threads the
# caller's value verbatim; spoke-ci-restricted must match site for site.
repo-role-census-contract-check:
    cd {{ root }} && ruby scripts/repo-role-census-contract.rb

# Prove that checker rejects a site left hardcoded (either one), a silently
# widened or narrowed default, an undeclared input, a dropped required_roles, a
# NEW census site added without threading the input, and restricted-variant drift.
repo-role-census-contract-selftest:
    cd {{ root }} && ruby scripts/repo-role-census-contract.rb --self-test

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

# Prove the manifest validator routes each schema_version to ITS schema, fails
# an unpublished version loudly instead of falling back to v1, fails closed on
# an invalid manifest, and — with `jsonschema` hidden — REFUSES to answer at all
# rather than substituting a weaker engine. The refusal cases are the ones that
# go red if a fallback validator is ever reintroduced.
# TIN-2109 (routing); TIN-4132/TIN-4192 (one engine, or no verdict).
manifest-validate-selftest:
    cd {{ root }} && bash scripts/manifest-schema-validate-selftest.sh

# Scan current files for secrets.
secrets-scan-dir:
    cd {{ root }} && gitleaks dir --config .gitleaks.toml --redact --verbose .

# Scan git history for secrets.
secrets-scan:
    cd {{ root }} && gitleaks git --config .gitleaks.toml --redact --verbose .
