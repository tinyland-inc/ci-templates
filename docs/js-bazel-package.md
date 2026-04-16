# JS Bazel Package Workflow

`js-bazel-package.yml` is the reusable workflow for JavaScript/TypeScript packages whose authoritative publish artifact is built by Bazel rather than published directly from the workspace tree.

It is meant for packages like:

- `@tummycrypt/scheduling-kit`
- `@tummycrypt/tinyvectors`
- `@tummycrypt/scheduling-bridge`

## What it does

- installs the workspace with pnpm
- runs optional metadata, lint, typecheck, unit, and integration commands
- builds the workspace artifact
- validates the Bazel-built package via `npm pack --dry-run`
- validates npm publish dry-runs against the Bazel artifact
- optionally validates GitHub Packages dry-runs after rewriting package metadata
- uploads the Bazel-built package artifact for publish jobs

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

- `bazel_targets` is space-delimited so callers can validate `//:pkg` alone or include extra targets like `//:typecheck` and `//:test`.
- `package_dir` should point at the Bazel-built publishable package directory, not the workspace root.
- `github_package_name` is optional. Leave it empty to skip GitHub Packages dry-runs and publish steps.
