# Rust Bazel Application Workflow

`rust-bazel-application.yml` is the opt-in, default-off CI contract for a
Rust application whose build, test, and package authority is Bazel. It was
introduced for the Prompt Pulse Rust productization canary, but it contains no
Prompt Pulse repository names, endpoints, runner labels, or release claims.

## Contract

The workflow does nothing unless `enabled: true`. An enabled caller supplies:

- an exact native platform matrix; every entry names `darwin` or `linux`,
  `aarch64` or `x86_64`, the exact runner label array, and one exact Bazel
  platform label;
- finite, non-empty JSON arrays of exact Bazel labels for rustfmt, clippy,
  application builds, unit tests, integration tests, and packages;
- tracked `.bazelversion`, `MODULE.bazel`, and `MODULE.bazel.lock` files.

Each selected native runner must already provide Bash, Git, Python 3, and
`bazelisk`. Tool installation and runner enrollment belong to the caller's
reproducible developer environment and operator overlay, not this workflow.

The contract rejects recursive target patterns, wildcards, shorthand package
labels, duplicate labels, an OS/architecture mismatch between the requested
lane and assigned runner, and a `.bazelversion` outside the requested major.
The default required major is Bazel 9. `bazelisk mod deps
--lockfile_mode=update` must leave the tracked lock file unchanged.

Rustfmt and clippy are Bazel test targets. This workflow does not add a second
Cargo CI authority, invoke repository-specific shell commands, select a remote
executor, publish packages, or infer a runner.

## Native platform scope

The matrix is caller-owned because runner capacity is an operator-overlay
fact. A two-lane consumer can use this shape after replacing the example
capability labels and platform labels with values its runner overlay and Bazel
graph actually serve:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  rust:
    uses: tinyland-inc/ci-templates/.github/workflows/rust-bazel-application.yml@vX.Y.Z
    with:
      enabled: true
      platform_matrix_json: >-
        [
          {"name":"darwin-aarch64","os":"darwin","arch":"aarch64","runner_labels":["tinyland-nix-darwin-aarch64"],"bazel_platform":"//platforms:aarch64-apple-darwin"},
          {"name":"linux-x86_64","os":"linux","arch":"x86_64","runner_labels":["tinyland-nix-linux-x86_64"],"bazel_platform":"//platforms:x86_64-linux-musl"}
        ]
      rustfmt_targets_json: '["//tools/quality:rustfmt_test"]'
      clippy_targets_json: '["//tools/quality:clippy_test"]'
      build_targets_json: '["//crates/client:prompt-pulse","//crates/daemon:prompt-pulsed"]'
      unit_test_targets_json: '["//crates/core:unit_tests"]'
      integration_test_targets_json: '["//tests:protocol_integration"]'
      package_targets_json: '["//packaging:release_archives"]'
```

Those two entries are an interface example, not a claim that the labels are
currently served. The workflow proves only platforms that a caller explicitly
provides and that GitHub assigns natively. It does not claim a four-platform
matrix, cross-built release parity, or any GloriousFlywheel remote-execution
support.

## GloriousFlywheel cache policy

Cache attachment is independently opt-in with `cache_enabled: true`. The
workflow source contains no endpoint, credential, auth header, or executor.
Runtime authority is passed through the optional secrets
`GF_BAZEL_REMOTE_CACHE`, `GF_BAZEL_REMOTE_HEADER`,
`GF_BAZEL_REMOTE_CACHE_HEADER`, and `GF_BAZEL_CREDENTIAL_HELPER`. The shared
cache-attachment contract fails closed when an opted lane lacks a real cache or
an eligible capability runner.

Remote cache reads are permitted on any opted lane. Uploads require all of the
following:

1. `trusted_cache_upload: true`;
2. a `push` event, never a pull request or `pull_request_target` event;
3. `github.ref_protected == true` from GitHub rulesets/branch protection; and
4. either the configured protected branch (default `main`) or a protected tag
   with the configured prefix (default `v`).

Every other cache-backed run passes
`--remote_upload_local_results=false`. This is cache-first only: no input,
secret, flag, or source path enables a remote executor.

Example runtime attachment:

```yaml
    secrets:
      GF_BAZEL_REMOTE_CACHE: ${{ secrets.GF_BAZEL_REMOTE_CACHE }}
      GF_BAZEL_REMOTE_HEADER: ${{ secrets.GF_BAZEL_REMOTE_HEADER }}
```

Leave `cache_enabled` and `trusted_cache_upload` false until the consuming
repository has an enrolled GloriousFlywheel cache path and protected-ref
ruleset. Package targets validate artifacts; release publication remains a
separate, attested release workflow.
