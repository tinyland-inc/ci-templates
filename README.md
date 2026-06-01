# ci-templates

Reusable GitHub Actions composite actions + reusable workflows for the
Tinyland CI house style.

> ⚠️ **Pin to an immutable release tag such as `@v2.0.0`.** `@main` is the develop branch and
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
- **Scaffold AX/skills inheritance** via `inherit-scaffold-skills`, which
  pulls `plugins/scaffold-core` from `tinyland-inc/site.scaffold` at a pinned
  tag.
- **Repo-shape manifest validation** via `repo-manifest-validate`.
- **Schema-validated `lanes.json` loading** via `lanes-load`.
- **Blahaj `repository_dispatch` payload construction** via
  `lane-dispatch` / `lane-reap`.
- **Public client preview dispatch** via `public-preview-dispatch`;
  Blahaj owns Cloudflare DNS, Access, Tunnel ingress, and cleanup.
- **Scheduled expired-lane cleanup dispatch** via `lane-ttl-reap`.
- **GloriousFlywheel proof dispatch** via `flywheel-reapi-proof`.
- **Per-lane GitHub commit status checks** via `lane-status-check`.

The full contract spokes conform to is
[`tinyland-inc/site.scaffold/docs/CI-SCHEMA.md`](https://raw.githubusercontent.com/tinyland-inc/site.scaffold/main/docs/CI-SCHEMA.md).

## Quick start

```yaml
# .github/workflows/ci.yml
jobs:
  ci:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v2.0.0
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
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-lane-env.yml@v2.0.0
    with:
      spoke: my-spoke
      enable_tailnet_qa: false
    secrets:
      BLAHAJ_DISPATCH_TOKEN: ${{ secrets.BLAHAJ_DISPATCH_TOKEN }}
```

Your spoke needs `.github/lanes.json` validating against
[`schemas/lanes.schema.json`](./schemas/lanes.schema.json). New spokes should
also include `tinyland.repo.json` validating against
[`schemas/tinyland-repo-manifest.schema.json`](./schemas/tinyland-repo-manifest.schema.json).

To inherit the canonical scaffold agent skills into a spoke:

```yaml
steps:
  - uses: actions/checkout@v6
  - uses: tinyland-inc/ci-templates/.github/actions/inherit-scaffold-skills@v2.0.0
    with:
      scaffold_ref: v2026.05.19
```

`scaffold_ref` must be a pinned scaffold tag, `refs/tags/*`, or a full commit
SHA. Branch refs such as `main` are rejected by default.

## Local validation

Use the same house-style entrypoint as consuming repos:

```bash
just check
nix develop --command just check
```

The check parses all workflow/action YAML, parses vendored JSON schemas,
validates `tinyland.repo.json`, verifies v2 internal action refs resolve to
checked-in sibling actions, asserts `bazelrc/flywheel.bazelrc` remains
endpoint-free, and runs the canonical Tinyland gitleaks working-tree scan.

## Composite actions

| Action | Purpose |
|---|---|
| `nix-setup` | Configure Nix + cache hints. Does not invent Bazel endpoints. |
| `nix-build` | Run `nix build` with Attic binary cache. |
| `greedy-cache` | Start Attic `watch-store` daemon for concurrent push. |
| `secrets-scan` | TruffleHog + Gitleaks. |
| **`inherit-scaffold-skills`** | Pull `plugins/scaffold-core` from `site.scaffold` at a pinned ref and materialize `.agents/skills` + `.claude/skills`. |
| **`repo-manifest-validate`** | Validate `tinyland.repo.json` and optionally require repo roles such as `static-spoke`. |
| **`flywheel-bazel`** | `bazelisk` wrapper with endpoint-free `--config=flywheel[-executor]`. Supplies cache/executor endpoints from runtime env or inputs. Refuses executor on non-cluster runners. |
| **`lanes-load`** | Validate + load `.github/lanes.json`. Outputs matrix-ready `lanes_json`. |
| **`lane-dispatch`** | Emit Blahaj `<spoke>-lane-env` provision payload. Supports `dry_run`. |
| **`lane-reap`** | Emit Blahaj destroy payload. Idempotent. |
| **`lane-ttl-reap`** | Emit Blahaj expired-lane sweep payload for scheduled TTL backstops. |
| **`public-preview-dispatch`** | Emit Blahaj public/client preview payload with Cloudflare Access allowlist. |
| **`flywheel-reapi-proof`** | Dispatch and optionally await a GloriousFlywheel executor-backed proof run, correlated by a unique request id. |
| **`lane-status-check`** | Post per-lane `ci/lane/<name>` GitHub commit status. |
| **`pulse-ingest-validate`** | Validate a Pulse / static projection snapshot. |

See per-action `action.yml` files for full input/output documentation.

## Reusable workflows

| Workflow | Purpose |
|---|---|
| `js-bazel-package.yml` | Pre-existing: JS/TS packages built by Bazel and published to GitHub Packages, with npmjs required/optional/disabled by package policy. |
| `npm-publish.yml` | Pre-existing: hosted-only Node package build + publish. |
| **`spoke-ci.yml`** | Canonical spoke CI: secrets-scan, lanes-load, per-lane flywheel-bazel build/test, bazel-graph, optional Playwright. |
| **`spoke-lane-env.yml`** | Canonical PR-env workflow. Replaces hand-rolled `pr-env-lanes.yml`. |
| **`spoke-lane-ttl-reap.yml`** | Reusable scheduled TTL backstop dispatcher for Blahaj lane cleanup. |
| **`spoke-public-preview.yml`** | Reusable public/client preview dispatcher for Cloudflare Access-gated aliases. |
| **`spoke-pulse-ingest.yml`** | Snapshot-refresh PR opener. |

## Schemas

`schemas/tinyland-repo-manifest.schema.json`, `schemas/lanes.schema.json`,
`schemas/blahaj-dispatch.schema.json`, `schemas/lane-ttl-reap-dispatch.schema.json`, and
`schemas/public-preview-dispatch.schema.json`
are vendored from `tinyland-inc/site.scaffold/docs/schemas/`. The
schema-doc repo is the source of truth; this repo vendors at known
stable paths so composite actions can `jsonschema` against them.

## Bazelrc fragment

`bazelrc/flywheel.bazelrc` is endpoint-free. It defines safe behavior for
`--config=flywheel` and `--config=flywheel-executor`, but does not hard-code
`remote_cache`, `remote_executor`, credentials, headers, or upload authority.
The `flywheel-bazel` composite installs it at runtime and supplies
`--remote_cache` from `BAZEL_REMOTE_CACHE`; executor mode additionally requires
`BAZEL_REMOTE_EXECUTOR`. Pull requests default to read-only cache use unless a
trusted lane sets `GF_BAZEL_REMOTE_UPLOAD=true`.

## Contributing

See [`RELEASING.md`](./RELEASING.md) for the release flow and SemVer
policy. Each PR must amend `## [Unreleased]` in `CHANGELOG.md`. Internal
composite-to-composite refs must use the current floating major tag, not
`@main` or an older major.

## Migration from `@main`

See [`docs/migration-v0-to-v1.md`](docs/migration-v0-to-v1.md) and
[`docs/migration-v1-to-v2.md`](docs/migration-v1-to-v2.md).
