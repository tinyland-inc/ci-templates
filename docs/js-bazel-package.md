# JS Bazel Package Workflow

`js-bazel-package.yml` is the reusable workflow for JavaScript/TypeScript packages whose authoritative publish artifact is built by Bazel rather than published directly from the workspace tree.

It is meant for packages like:

- `@tummycrypt/scheduling-kit`
- `@tummycrypt/tinyvectors`
- `@tummycrypt/scheduling-bridge`

## What it does

- installs the workspace with pnpm
- optionally cleans stale self-hosted workspace artifacts before install or publish extraction
- optionally runs a repo-specific prepare step after install
- runs optional metadata, lint, typecheck, unit, and integration commands
- builds the workspace artifact
- validates the Bazel-built package via `npm pack --dry-run`
- validates npm publish dry-runs against the Bazel artifact
- optionally validates GitHub Packages dry-runs after rewriting package metadata
- uploads the Bazel-built package artifact for publish jobs
- preserves npm provenance on GitHub-hosted runners while skipping it on self-hosted runners when needed

## Example

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
      runner_labels_json: ${{ vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '["ubuntu-latest"]' }}
      cleanup_paths: "pkg pkg-github dist node_modules .svelte-kit bazel-bin bazel-out bazel-testlogs .pnpm-store bazel-pkg.tgz MODULE.bazel.lock"
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

## Notes

- `runner_labels_json` lets callers preserve self-hosted runner routing instead of hard-coding `ubuntu-latest` into each package repo.
- `cleanup_paths` is useful on long-lived self-hosted runners where stale `dist/`, Bazel outputs, or old package artifacts can poison later runs.
- `prepare_command` is where SvelteKit callers should run `pnpm exec svelte-kit sync` before typecheck or build.
- `bazel_targets` is space-delimited so callers can validate `//:pkg` alone or include extra targets like `//:typecheck` and `//:test`.
- `package_dir` should point at the Bazel-built publishable package directory, not the workspace root.
- `github_package_name` is optional. Leave it empty to skip GitHub Packages dry-runs and publish steps.
- npmjs publication uses `--provenance` by default, but the reusable workflow will skip it automatically on self-hosted runners.
