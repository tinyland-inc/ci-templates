# JS Bazel Package Workflow

`js-bazel-package.yml` is the reusable workflow for JavaScript and TypeScript
packages whose authoritative publish artifact is built by Bazel rather than
published directly from the workspace tree.

It is meant for packages like:

- `@tummycrypt/scheduling-kit`
- `@tummycrypt/tinyvectors`
- `@tummycrypt/scheduling-bridge`

## What it does

- makes runner intent explicit with `runner_mode`
- makes workspace hygiene explicit with `workspace_mode`
- makes publish authority explicit with `publish_mode`
- makes npmjs authority explicit with `npm_publish_mode`
- installs the workspace with pnpm
- configures Attic and Bazel cache hints on self-hosted runners
- optionally keeps legacy cleanup-based workspace behavior for migration
- optionally stages validation work in an isolated scratch workspace
- runs optional metadata, lint, typecheck, unit, and integration commands
- builds the workspace artifact
- validates the Bazel-built package via `npm pack --dry-run`
- validates npm publish dry-runs against the Bazel artifact unless npmjs is
  disabled
- optionally validates GitHub Packages dry-runs after rewriting package metadata
- uploads the Bazel-built package artifact for publish jobs
- publishes from the same runner class or from an explicit hosted exception path

## Contract inputs

### `runner_mode`

Allowed values:

- `compat`
- `hosted`
- `shared`
- `repo_owned`

Meaning:

- `compat`
  - preserve the legacy `runner_labels_json` behavior
  - use this only as a migration bridge
- `hosted`
  - validate and publish on GitHub-hosted runners intentionally
- `shared`
  - validate and publish on a documented shared GloriousFlywheel lane
  - pass a non-empty `shared_runner_labels_json`; an empty value is rejected
    because it usually means the caller repo variable is missing
  - labels must include one of the shared Tinyland capability classes
- `repo_owned`
  - validate and publish on a repo/owner-scoped runner registration path
  - workflow-facing labels still stay shared Tinyland capability classes
  - labels must include one of the shared Tinyland capability classes

`repo_owned` is a trust and registration boundary, not permission to mint
repo-shaped runner labels. GloriousFlywheel keeps runner labels capability-based
(`tinyland-nix`, `tinyland-docker`, and related classes); owner/repo separation
belongs in ARC registration identity, runner groups, GitHub App installation,
and implementation-overlay policy.

### `workspace_mode`

Allowed values:

- `isolated`
- `persistent_compat`

Meaning:

- `isolated`
  - checkout normally
  - copy the repo into a per-job scratch directory under `$RUNNER_TEMP`
  - run validation there
- `persistent_compat`
  - keep the old cleanup-based model for long-lived self-hosted workspaces

### `publish_mode`

Allowed values:

- `same_runner`
- `hosted_exception`

Meaning:

- `same_runner`
  - publish from the same runner class that validated the Bazel artifact
- `hosted_exception`
  - validate on the chosen runner class
  - publish from `ubuntu-latest` intentionally after artifact handoff

### `npm_publish_mode`

Allowed values:

- `required`
- `optional`
- `disabled`

Meaning:

- `required`
  - preserve the legacy npmjs contract
  - validate npmjs dry-runs
  - require `secrets.NPM_TOKEN` before real npmjs publication
  - fail the workflow when npmjs publish fails
- `optional`
  - keep npmjs validation and publication as best-effort compatibility
  - skip real npmjs publication when `secrets.NPM_TOKEN` is absent
  - warn, but do not fail, when npmjs dry-run or publish fails
- `disabled`
  - skip npmjs dry-run validation and npmjs publication
  - use this for Bazel-first packages whose release authority is GitHub
    tag/release, GitHub Packages, and the Tinyland Bazel registry

### `cache_backed`

Opt-in (default `false`) shared-cache-backed Bazel validation. This is the
TIN-2110 cache-first enrollment surface (TIN-1997 Option D, proven by GF#889).

- `false` / unset (default)
  - the Bazel target validation runs the existing plain
    `npx --yes @bazel/bazelisk build <targets> --verbose_failures` path,
    byte-identically. Non-opted consumers see zero behavior change.
- `true`
  - the consumer's `tinyland.repo.json` is validated against the vendored
    ci-templates schema (network-free); an invalid manifest **fails closed**
    (TIN-2109)
  - a fail-closed cache-attachment contract step runs next
    (`scripts/cache-attachment-contract.sh --strict`), rejecting unexpanded
    `${...}` placeholders, non-`grpc`/`http` endpoints, and localhost endpoints
    (unless `GF_BAZEL_ALLOW_LOCALHOST_PROOF=true`)
  - the contract's **expected mode is manifest-driven** (TIN-2109): it is read
    from `enrollment.substrateMode` in `tinyland.repo.json`. If the manifest
    declares `shared-cache-backed` but no cache actually attaches, the lane
    **fails closed** (declared-vs-actual mismatch) instead of silently degrading
  - the workflow exports `GF_FLYWHEEL_PROFILE_STATE` from the resolved substrate
    mode so consumer `flywheel-doctor` / `flywheel-verify` commands see the
    same machine-readable attachment state as CI
  - the contract **rejects hosted / repo-shaped runner fallback**: the runner
    labels are inspected and a GitHub-hosted (`ubuntu-*`), bare `self-hosted`, or
    repo-shaped (`<name>-nix*`) runner is a deterministic failure, never a silent
    degrade to a hosted build (override only with
    `GF_BAZEL_ALLOW_HOSTED_RUNNER=true`)
  - the Bazel validation then runs
    `--config=ci-cached --remote_cache=$BAZEL_REMOTE_CACHE
    --remote_upload_local_results=false`, reading the shared Bazel cache
  - the lane fails closed when `BAZEL_REMOTE_CACHE` is unset rather than
    silently building local-only

`cache_backed` is **cache-first only**. It never wires a remote executor; REAPI /
remote execution is out of scope for this lane (the workflow contains no
executor flag or endpoint). On self-hosted Tinyland cluster runners, `nix-setup`
exports `BAZEL_REMOTE_CACHE` from cluster DNS, so attach needs no new secret or
infrastructure; off-cluster, supply the endpoint via a repo/org secret or a
wrapping step before validation.

The contract script also **defines and enforces** the `executor-backed` contract
for any repo that declares `enrollment.substrateMode: executor-backed`: it then
requires the full set (remote executor endpoint + `BAZEL_REMOTE_CACHE` + a
cluster runner class for platform identity + a digest-pinned REAPI proof image,
`GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST`) and fails closed if any piece is missing.
**No current repo selects executor-backed** (cache-first / Option D); the contract
is defined so the gate is enforceable the moment a repo declares it.

Consumers opting in must:

1. set `cache_backed: true` in the `with:` block
2. vendor `bazelrc/ci-cached.bazelrc` behavior in their `.bazelrc` (a base `:ci`
   config that empties `--disk_cache=` in CI plus the `:ci-cached` block) so a
   green build proves the **remote** cache, not an incidental disk hit
3. optionally vendor `scripts/cache-attachment-contract.sh` for the same
   fail-closed self-check locally (`scripts/cache-attachment-contract.sh
   --strict`); the workflow falls back to fetching the pinned ci-templates copy
   when the consumer has not vendored it

Real enrollment is proven by remote cache hit/transfer lines in the cache-backed
validation step log. A green build that shows only `--disk_cache` and no remote
transfer is **not** enrollment.

When the consumer has not vendored `scripts/cache-attachment-contract.sh`, the
workflow fetches it from an **immutable releasing tag** (the fallback ref is
pinned to `v2.5.1`, not the floating `v2` major), so pure-consumer spokes get a
reproducible fetch.

### `substrate_mode`

Optional operator override for the cache-backed lane's expected substrate mode
(`compatibility-local-only` | `shared-cache-backed` | `executor-backed`). It is
used **only** when `cache_backed: true` and the consumer's `tinyland.repo.json`
does not declare `enrollment.substrateMode` — the manifest is the authoritative
source (TIN-2109). When both are empty the lane defaults to
`shared-cache-backed`. This input has no effect on the default
(non-cache-backed) path.

### `github_package_name`

`github_package_name` is the package coordinate used only for the GitHub
Packages artifact. It may intentionally differ from the npmjs package name.

GitHub Packages npm scopes are owner-bound, so the scope must match the GitHub
account or organization that owns the package. For a `tinyland-inc/*` repository
whose public npm package is `@tummycrypt/tinyland-auth`, use a GitHub Packages
mirror name such as `@tinyland-inc/tinyland-auth`.

## Example: repo-owned capability-class package path

```yaml
name: CI

on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v2.0.0
    with:
      runner_mode: repo_owned
      runner_labels_json: ${{ vars.PRIMARY_LINUX_RUNNER_LABELS_JSON }}
      workspace_mode: isolated
      publish_mode: same_runner
      prepare_command: pnpm exec svelte-kit sync
      metadata_check_command: pnpm check:release-metadata
      lint_command: pnpm lint
      typecheck_command: pnpm check
      unit_test_command: pnpm test:unit
      integration_test_command: pnpm test:integration
      build_command: pnpm build
      package_check_command: pnpm check:package
      bazel_targets: "//:typecheck //:pkg //:test"
      package_dir: ./bazel-bin/pkg
      github_package_name: "@jesssullivan/scheduling-kit"
      npm_publish_mode: required
      dry_run: true
      publish_on_tag: true
    secrets: inherit
```

In that example, `PRIMARY_LINUX_RUNNER_LABELS_JSON` must resolve to a
capability-shaped label set such as `["self-hosted","linux","tinyland-nix"]`.
It must not resolve to a repo-shaped label. Pull-request validation remains
safe for forks because publish jobs are still gated by tag/workflow policy and
GitHub does not expose protected publish secrets to untrusted fork PRs.

## Example: hosted template consumer

```yaml
on:
  push:
    tags: ['v*']
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v2.0.0
    with:
      runner_mode: hosted
      workspace_mode: isolated
      publish_mode: hosted_exception
      lint_command: pnpm lint
      typecheck_command: pnpm typecheck
      unit_test_command: pnpm test
      build_command: pnpm build
      bazel_targets: "//:pkg"
      package_dir: ./bazel-bin/pkg
      github_package_name: "@tinyland-inc/tinyland-auth-redis"
      npm_publish_mode: disabled
      dry_run: true
      publish_on_tag: true
```

## Notes

- `compat` exists only to let existing consumers adopt the new template without
  breaking in one PR.
- `runner_mode=repo_owned` must pass explicit `runner_labels_json` and that
  label set must include a Tinyland capability class. It does not authorize
  repo-shaped labels.
- `runner_mode=shared` uses `shared_runner_labels_json`. The workflow resolves
  the selected labels in a small hosted setup job, then passes simple JSON
  outputs into `runs-on` to avoid the complex inline expressions that previously
  caused GitHub Actions startup failures before jobs were created.
- `runner_mode=shared` rejects an explicitly empty `shared_runner_labels_json`.
  This catches missing caller repo variables before the workflow silently falls
  back to the default shared runner class.
- Package repos that need fork-safe owned capacity should prefer
  `runner_mode=repo_owned` with explicit capability-shaped
  `runner_labels_json`. Use `hosted` for packages that do not need
  cluster-internal REAPI access yet.
- `bazel_fetch_retry_attempts` defaults to `3` and wraps consumer-provided
  validation commands plus explicit Bazel target validation. It only retries
  when the command log matches transient Bazel external archive fetch failures,
  such as upstream GitHub release `502` responses. Deterministic compile/test
  failures are not retried.
- `publish_mode=hosted_exception` intentionally overrides the selected runner
  lane for publish jobs and uses `ubuntu-latest`.
- `dry_run: true` keeps pull requests and branch pushes in validation-only mode.
  Set `publish_on_tag: true` in package repositories that should publish the
  Bazel artifact when the caller workflow is triggered by a `push` to `refs/tags/v*`.
  The caller workflow must include an `on.push.tags` trigger. npmjs publication
  requires `secrets.NPM_TOKEN` only when `npm_publish_mode=required`; Bazel-first
  packages should use `optional` or `disabled` when GitHub Packages and the
  Bazel registry are the release authority.
- self-hosted jobs now call `nix-setup`, so Attic and Bazel cache hints are
  explicit instead of incidental runner state.
- `workspace_mode=isolated` is the preferred contract for downstream pilots.
- `cleanup_paths` is still available, but only applies to
  `workspace_mode=persistent_compat`.
- publish jobs always extract into an isolated temp directory, even when the
  validation workspace stays in compatibility mode.
- npmjs publication still requests provenance on hosted runners and skips it on
  self-hosted runners when needed, but only when `npm_publish_mode` allows an
  npmjs publish attempt.
- real publish jobs are idempotent for already-published package versions. After
  extracting the Bazel artifact, the npmjs and GitHub Packages jobs check
  whether the exact `name@version` already exists in the target registry and
  skip only that duplicate-version case. Registry lookup failures or absent
  versions still fall through to `npm publish` so permission and package errors
  remain visible unless `npm_publish_mode=optional`.
- npm publish dry-run validation also treats npm's duplicate-version rejection
  as an idempotent pass. Newer npm versions may reject `npm publish --dry-run`
  for an already-published version even though the preceding `npm pack`
  validation proved the package artifact shape. Use `npm_publish_mode=disabled`
  to skip npmjs dry-run validation entirely for Bazel-first packages with no
  npmjs release target.
