# ci-templates

Reusable GitHub Actions composite actions + reusable workflows for the
Tinyland CI house style.

> ⚠️ **Pin to `@v1.0.0` or later.** `@main` is the develop branch and
> may break without notice. See [`RELEASING.md`](./RELEASING.md) for the
> SemVer contract.

Spokes spawned from `tinyland-inc/site.scaffold` consume this repo for:

- **Spoke CI** (lint, type-check, build, test, Bazel graph, optional
  Playwright) via `spoke-ci.yml` reusable workflow.
- **Per-PR ephemeral env lifecycle** (build image, dispatch to Blahaj,
  reap on close) via `spoke-lane-env.yml`.
- **Static projection snapshot refresh** via `spoke-pulse-ingest.yml`.
- **GloriousFlywheel REAPI binding** via the `flywheel-bazel` composite
  action.
- **Schema-validated `lanes.json` loading** via `lanes-load`.
- **Blahaj `repository_dispatch` payload construction** via
  `lane-dispatch` / `lane-reap`.
- **Per-lane GitHub commit status checks** via `lane-status-check`.

The full contract spokes conform to is
[`tinyland-inc/site.scaffold/docs/CI-SCHEMA.md`](https://raw.githubusercontent.com/tinyland-inc/site.scaffold/main/docs/CI-SCHEMA.md).

## Quick start

```yaml
# .github/workflows/ci.yml
jobs:
  ci:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v1.0.0
    with:
      flywheel_config: flywheel-executor
      playwright_enabled: true
    secrets: inherit
```

```yaml
# .github/workflows/lane-env.yml
on:
  pull_request:
    types: [opened, synchronize, reopened, closed]

jobs:
  lane-env:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-lane-env.yml@v1.0.0
    with:
      spoke: my-spoke
      enable_tailnet_qa: false
    secrets:
      BLAHAJ_DISPATCH_TOKEN: ${{ secrets.BLAHAJ_DISPATCH_TOKEN }}
```

Your spoke needs `.github/lanes.json` validating against
[`schemas/lanes.schema.json`](./schemas/lanes.schema.json).

## Composite actions

| Action | Purpose |
|---|---|
| `nix-setup` | Configure Nix + cache endpoints. Auto-detects cluster reachability. |
| `nix-build` | Run `nix build` with Attic binary cache. |
| `greedy-cache` | Start Attic `watch-store` daemon for concurrent push. |
| `secrets-scan` | TruffleHog + Gitleaks. |
| **`flywheel-bazel`** | `bazelisk` wrapper with `--config=flywheel[-executor]`. Refuses executor on non-cluster runners. |
| **`lanes-load`** | Validate + load `.github/lanes.json`. Outputs matrix-ready `lanes_json`. |
| **`lane-dispatch`** | Emit Blahaj `<spoke>-lane-env` provision payload. Supports `dry_run`. |
| **`lane-reap`** | Emit Blahaj destroy payload. Idempotent. |
| **`lane-status-check`** | Post per-lane `ci/lane/<name>` GitHub commit status. |
| **`pulse-ingest-validate`** | Validate a Pulse / static projection snapshot. |

Bolded actions are new in v1.0.0. See per-action `action.yml` for full
input/output documentation.

## Reusable workflows

| Workflow | Purpose |
|---|---|
| `js-bazel-package.yml` | Pre-existing: JS/TS packages built by Bazel and published to npm/GHCR. |
| `npm-publish.yml` | Pre-existing: hosted-only Node package build + publish. |
| **`spoke-ci.yml`** | Canonical spoke CI: secrets-scan, lanes-load, per-lane flywheel-bazel build/test, bazel-graph, optional Playwright. |
| **`spoke-lane-env.yml`** | Canonical PR-env workflow. Replaces hand-rolled `pr-env-lanes.yml`. |
| **`spoke-pulse-ingest.yml`** | Snapshot-refresh PR opener. |

## Schemas

`schemas/lanes.schema.json` and `schemas/blahaj-dispatch.schema.json`
are vendored from `tinyland-inc/site.scaffold/docs/schemas/`. The
schema-doc repo is the source of truth; this repo vendors at known
stable paths so composite actions can `jsonschema` against them.

## Bazelrc fragment

`bazelrc/flywheel.bazelrc` defines `--config=flywheel` (cache-only) and
`--config=flywheel-executor` (cache + REAPI executor). The
`flywheel-bazel` composite installs it at runtime; spokes also vendor a
copy at `.bazelrc.flywheel` and refresh via `just sync-flywheel-bazelrc`.

## Contributing

See [`RELEASING.md`](./RELEASING.md) for the release flow and SemVer
policy. Each PR must amend `## [Unreleased]` in `CHANGELOG.md`. Internal
composite-to-composite refs must use `@v1` (the floating major tag), not
`@main`.

## Migration from `@main`

See [`docs/migration-v0-to-v1.md`](docs/migration-v0-to-v1.md).
