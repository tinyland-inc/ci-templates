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
- installs the workspace with pnpm
- configures Attic and Bazel cache hints on self-hosted runners
- optionally keeps legacy cleanup-based workspace behavior for migration
- optionally stages validation work in an isolated scratch workspace
- runs optional metadata, lint, typecheck, unit, and integration commands
- builds the workspace artifact
- validates the Bazel-built package via `npm pack --dry-run`
- validates npm publish dry-runs against the Bazel artifact
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

## Example: repo-owned self-hosted package path

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@main
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
      dry_run: true
    secrets: inherit
```

## Example: hosted template consumer

```yaml
jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@main
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
      dry_run: true
```

## Notes

- `compat` exists only to let existing consumers adopt the new template without
  breaking in one PR.
- `runner_mode=repo_owned` should always pass explicit `runner_labels_json`.
- `runner_mode=shared` uses `shared_runner_labels_json`, which defaults to
  `["tinyland-docker"]`.
- `publish_mode=hosted_exception` intentionally overrides the selected runner
  lane for publish jobs and uses `ubuntu-latest`.
- self-hosted jobs now call `nix-setup`, so Attic and Bazel cache hints are
  explicit instead of incidental runner state.
- `workspace_mode=isolated` is the preferred contract for downstream pilots.
- `cleanup_paths` is still available, but only applies to
  `workspace_mode=persistent_compat`.
- publish jobs always extract into an isolated temp directory, even when the
  validation workspace stays in compatibility mode.
- npmjs publication still requests provenance on hosted runners and skips it on
  self-hosted runners when needed.
