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
- `repo_owned`
  - validate and publish on repo-specific runner labels

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

### `github_package_name`

`github_package_name` is the package coordinate used only for the GitHub
Packages artifact. It may intentionally differ from the npmjs package name.

GitHub Packages npm scopes are owner-bound, so the scope must match the GitHub
account or organization that owns the package. For a `tinyland-inc/*` repository
whose public npm package is `@tummycrypt/tinyland-auth`, use a GitHub Packages
mirror name such as `@tinyland-inc/tinyland-auth`.

## Example: repo-owned self-hosted package path

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
- `runner_mode=repo_owned` should always pass explicit `runner_labels_json`.
- `runner_mode=shared` uses `shared_runner_labels_json`. The workflow resolves
  the selected labels in a small hosted setup job, then passes simple JSON
  outputs into `runs-on` to avoid the complex inline expressions that previously
  caused GitHub Actions startup failures before jobs were created.
- `runner_mode=shared` rejects an explicitly empty `shared_runner_labels_json`.
  This catches missing caller repo variables before the workflow silently falls
  back to the default shared runner class.
- Package repos that need fork-safe owned capacity should prefer
  `runner_mode=repo_owned` with explicit `runner_labels_json`. Use `hosted` for
  packages that do not need cluster-internal REAPI access yet.
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
