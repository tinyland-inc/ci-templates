# Rust Bazel Application Workflow

`rust-bazel-application.yml` is the opt-in, default-off CI contract for a
Rust application whose build, test, and package authority is Bazel. It was
introduced for the Prompt Pulse Rust productization canary, but it contains no
Prompt Pulse repository names, endpoints, product-specific/native-lane runner
labels, or release claims. A fixed GitHub-hosted admission job runs no caller
code and receives no secrets; private native runners are assigned only after it
accepts a private same-repository event, route, matrix, and finite targets.

## Contract

The workflow does nothing unless `enabled: true`. An enabled caller supplies:

- the exact reviewed `tinyland-infra` private runner group; the immutable
  preflight runs without caller checkout before any private native lane is
  scheduled, and callers cannot mint repo-shaped group/label pairs;
- an exact native platform matrix; every entry names `darwin` or `linux`,
  `aarch64` or `x86_64`, the exact runner label array, and one exact Bazel
  platform label;
- finite, non-empty JSON arrays of exact Bazel labels for rustfmt, clippy,
  application builds, unit tests, integration tests, and packages;
- bounded lane controls: 5-180 timeout minutes and 1-4 concurrent lanes;
- tracked `.bazelversion`, `MODULE.bazel`, and `MODULE.bazel.lock` files.

Each selected native runner must already provide Bash, Git, Python 3, and
`bazelisk`. Tool installation and runner enrollment belong to the caller's
reproducible developer environment and operator overlay, not this workflow.

The pre-scheduling contract admits only the owner group's shared `nix` or
`nix-heavy` capability and rejects hosted, bare `self-hosted`, cross-owner, and
repo-shaped runner labels; recursive target patterns including `:all` and
`:all-targets`; shorthand package labels; duplicate labels or platforms; and
matrices larger than four lanes. It also refuses public repositories, fork pull
requests, and `pull_request_target`. The lane contract then rejects an
OS/architecture mismatch between the requested lane and assigned runner and a
`.bazelversion` outside the requested major.
The default required major is Bazel 9. `bazelisk mod deps
--lockfile_mode=update` must leave the tracked lock file unchanged. Every later
build and test runs with `--lockfile_mode=error`, followed by a final tracked
lock cleanliness check.

Rustfmt and clippy are Bazel test targets. This workflow does not add a second
Cargo CI authority, invoke repository-specific shell commands, select a remote
executor, publish packages, or infer a native-lane runner.

## Native platform scope

The matrix is caller-owned because native runner capacity is an operator fact.
This release admits only `tinyland-infra` with `tinyland-nix` or
`tinyland-nix-heavy`. Bazel platform aliases are a shared contract: consumers define the applicable canonical
`//platforms:<rust-triple>` targets exactly as shown. A two-lane consumer can
use this shape after selecting only the native lanes its runner overlay and
Bazel graph actually serve:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  rust:
    uses: tinyland-inc/ci-templates/.github/workflows/rust-bazel-application.yml@v2.14.0
    with:
      enabled: true
      runner_group: tinyland-infra
      platform_matrix_json: >-
        [
          {"name":"darwin-aarch64","os":"darwin","arch":"aarch64","runner_labels":["tinyland-nix","macOS","ARM64"],"bazel_platform":"//platforms:aarch64-apple-darwin"},
          {"name":"linux-x86_64","os":"linux","arch":"x86_64","runner_labels":["tinyland-nix","Linux","X64"],"bazel_platform":"//platforms:x86_64-unknown-linux-gnu"}
        ]
      rustfmt_targets_json: '["//tools/quality:rustfmt_test"]'
      clippy_targets_json: '["//tools/quality:clippy_test"]'
      build_targets_json: '["//crates/client:prompt-pulse","//crates/daemon:prompt-pulsed"]'
      unit_test_targets_json: '["//crates/core:unit_tests"]'
      integration_test_targets_json: '["//tests:protocol_integration"]'
      package_targets_json: '["//packaging:release_archives"]'
```

`v2.14.0` is the first planned immutable release containing this workflow and
both of its internal actions. Do not replace that pin with `@v2` or `@main`.

Those two entries are an interface example, not a claim that the labels are
currently served. The workflow proves only platforms that a caller explicitly
provides and that GitHub assigns natively. It does not claim a four-platform
matrix, cross-built release parity, or any GloriousFlywheel remote-execution
support.

Public repositories, `pull_request_target`, and fork pull requests fail in the
hosted admission job; they never receive a private runner, caller checkout, or
cache credential. A private same-repository pull request may use the native
lanes. A public/open-source product needs a separate fork-safe hosted build; it
must not route public events into this native private-runner workflow.

## GloriousFlywheel cache policy

Cache attachment is independently opt-in with `cache_enabled: true`. The
workflow source contains no endpoint, credential value, auth-header value, or
executor.
Runtime authority is passed through the optional secrets
`GF_BAZEL_REMOTE_CACHE`, `GF_BAZEL_REMOTE_CACHE_READ_HEADER`, and
`GF_BAZEL_REMOTE_CACHE_WRITE_HEADER`. Every cache-enabled caller configures a
server-enforced read-only header. A distinct write header is additionally
required before trusted upload can be admitted. Read lanes never materialize
the write value. The endpoint itself must be credential-free: URL userinfo,
query strings, and fragments are rejected.
The shared cache-attachment contract fails closed when an opted lane lacks a
real cache or an eligible capability runner.

Remote cache reads are permitted on any opted lane. Uploads require all of the
following:

1. `trusted_cache_upload: true`;
2. a `push` event, never a pull request or `pull_request_target` event;
3. `github.ref_protected == true` from GitHub rulesets/branch protection; and
4. either the configured protected branch (default `main`) or a protected tag
   with the configured prefix (default `v`).

Every other cache-backed run passes
`--remote_upload_local_results=false`. Every Bazel invocation uses the startup
option `--ignore_all_rc_files`; CI behavior therefore cannot inherit remote
endpoints, headers, credential helpers, executors, or uploads from workspace,
system, or home rc files. The workflow then supplies its complete cache policy
on the command line and always forces `--remote_executor=`. This is cache-first
only: no input, secret, flag, or source path enables a remote executor.

The tracked `.bazelversion` is validated before use. Every invocation then goes
through a release-vendored driver that scrubs all Bazelisk configuration
variables, resets the exact version and wrapper prohibition, forces
`--ignore_all_rc_files`, and uses run-scoped `HOME`/`BAZELISK_HOME` roots under
`RUNNER_TEMP`; a workspace `.bazeliskrc` is rejected. Caller wrappers, download
redirects, runner-service overrides, user config, and cross-run Bazelisk cache
poisoning therefore cannot replace the validated Bazel binary or bypass the
command-line contract.

Example runtime attachment:

```yaml
    secrets:
      GF_BAZEL_REMOTE_CACHE: ${{ secrets.GF_BAZEL_REMOTE_CACHE }}
      GF_BAZEL_REMOTE_CACHE_READ_HEADER: ${{ secrets.GF_BAZEL_REMOTE_CACHE_READ_HEADER }}
      GF_BAZEL_REMOTE_CACHE_WRITE_HEADER: ${{ secrets.GF_BAZEL_REMOTE_CACHE_WRITE_HEADER }}
```

Leave `cache_enabled` and `trusted_cache_upload` false until the consuming
repository has an enrolled GloriousFlywheel cache path and protected-ref
ruleset. Package targets validate artifacts; release publication remains a
separate, attested release workflow.
