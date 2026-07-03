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
checked-in sibling actions, asserts `bazelrc/flywheel.bazelrc` and
`bazelrc/ci-cached.bazelrc` remain endpoint-free, asserts the `cache_backed`
opt-in lane stays default-off and cache-first, and runs the canonical Tinyland
gitleaks working-tree scan.

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
| `js-bazel-package.yml` | Pre-existing: JS/TS packages built by Bazel and published to GitHub Packages, with npmjs required/optional/disabled by package policy. Supports an **opt-in, default-off `cache_backed`** shared-cache Bazel validation lane (cache-first; see below). |
| `npm-publish.yml` | Pre-existing: hosted-only Node package build + publish. |
| **`spoke-ci.yml`** | Canonical spoke CI: secrets-scan, lanes-load, per-lane flywheel-bazel build/test, bazel-graph, optional Playwright. |
| **`spoke-lane-env.yml`** | Canonical PR-env workflow. Replaces hand-rolled `pr-env-lanes.yml`. |
| **`spoke-lane-ttl-reap.yml`** | Reusable scheduled TTL backstop dispatcher for Blahaj lane cleanup. |
| **`spoke-public-preview.yml`** | Reusable public/client preview dispatcher for Cloudflare Access-gated aliases. |
| **`spoke-pulse-ingest.yml`** | Snapshot-refresh PR opener. |
| **`spoke-deploy-cloudflare-pages.yml`** | Sanctioned **opt-in** Cloudflare Pages deploy lane. Builds the adapter-static `build/` via `nix develop --command just setup/check/build`, then `wrangler pages deploy build`. Credential-skips when the org CF secrets are absent; PR events build only. Does **not** replace the scaffold default GitHub-Pages lane. |

### Cloudflare Pages deploy lane (opt-in)

`spoke-deploy-cloudflare-pages.yml` DRYs the hand-rolled CF-Pages publisher that
was copied into multiple spokes (GFTB `greatfallstoolbus.org`,
`transscendsurvival.org`, and the `site.scaffold`
`docs/deploy/cloudflare-pages.md` template block). GitHub Pages remains the
scaffold **default** deploy lane (`deploy-pages.yml`); this is the sanctioned
CF-Pages **opt-in**, now reusable.

A spoke's thin `.github/workflows/deploy-pages.yml` becomes a wrapper:

```yaml
# .github/workflows/deploy-pages.yml
name: Deploy to Cloudflare Pages

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  deployments: write

jobs:
  deploy:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-deploy-cloudflare-pages.yml@v2.10.0
    secrets:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

`project_name` defaults to the slugified repository name (dots/underscores →
hyphens); override it with the `project_name` input when the CF project name
differs. The deploy step **skips with a `::notice::`** when
`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` are absent, so the wrapper
merges safely before the org token is minted (personal-account spokes never
hold CF creds). PR events build only — they never deploy and never mutate repo
state. Pin `@vX.Y.Z` to your intended release; the example above assumes the
first release that ships this lane.

## Schemas

`schemas/tinyland-repo-manifest.schema.json`, `schemas/lanes.schema.json`,
`schemas/blahaj-dispatch.schema.json`, `schemas/lane-ttl-reap-dispatch.schema.json`, and
`schemas/public-preview-dispatch.schema.json`
are vendored from `tinyland-inc/site.scaffold/docs/schemas/`. The
schema-doc repo is the source of truth; this repo vendors at known
stable paths so composite actions can `jsonschema` against them.

`tinyland-repo-manifest.schema.json` carries first-class, validated **enrollment**
fields (TIN-2109): `enrollment.forgeScope`, `enrollment.operatorOverlay`,
`enrollment.executionPool`, and `enrollment.substrateMode`
(`compatibility-local-only` | `shared-cache-backed` | `executor-backed`). The
object is additive and optional — existing manifests without it still validate —
and `substrateMode` is the authoritative expected mode the cache-backed gate
enforces.

## Bazelrc fragments

`bazelrc/flywheel.bazelrc` is endpoint-free. It defines safe behavior for
`--config=flywheel` and `--config=flywheel-executor`, but does not hard-code
`remote_cache`, `remote_executor`, credentials, headers, or upload authority.
The `flywheel-bazel` composite installs it at runtime and supplies
`--remote_cache` from `BAZEL_REMOTE_CACHE`; executor mode additionally requires
`BAZEL_REMOTE_EXECUTOR`. Pull requests default to read-only cache use unless a
trusted lane sets `GF_BAZEL_REMOTE_UPLOAD=true`.

`bazelrc/ci-cached.bazelrc` is the consumer-naming counterpart for the
**cache-first** lane. It defines endpoint-free `--config=ci-cached`,
`--config=cache-readonly`, and `--config=no-remote-cache` behavior that spoke
`.bazelrc` files reference. It is read-only by default (no upload) and never
selects a remote executor. `scripts/cache-attachment-contract.sh` is the
fail-closed checker that gates cache-backed work (`--strict` requires a real
`BAZEL_REMOTE_CACHE`; rejects unexpanded `${...}` placeholders, non-`grpc`/`http`
endpoints, and localhost without explicit proof).

## Cache-backed enrollment (cache-first, TIN-2110)

`js-bazel-package.yml` exposes an **opt-in, default-off** `cache_backed` input.
When unset, the Bazel validation runs the existing
`bazelisk build … --verbose_failures` path byte-identically — zero impact on
non-opted consumers. When `cache_backed: true`, the workflow runs the fail-closed
cache-attachment contract and then validates with
`--config=ci-cached --remote_cache=$BAZEL_REMOTE_CACHE
--remote_upload_local_results=false`, reading the shared Bazel cache. This lane is
cache-first only (TIN-1997 Option D / GF#889); it never wires a remote executor.
On self-hosted Tinyland cluster runners, `nix-setup` exports `BAZEL_REMOTE_CACHE`
from cluster DNS, so attach needs no new secret or infrastructure.

The cache-backed lane is **hardened for deterministic, fail-closed enrollment**
(TIN-2109): it validates the consumer's `tinyland.repo.json` against the schema,
reads `enrollment.substrateMode` as the authoritative expected mode (a
declared-vs-actual mismatch fails closed), rejects hosted / repo-shaped runner
fallback (no silent degrade to a GitHub-hosted build), and pins the contract-script
fetch fallback to an immutable releasing tag. It also exports
`GF_FLYWHEEL_PROFILE_STATE` from the resolved substrate mode so consumer
`flywheel-doctor` / `flywheel-verify` tooling sees the same machine-readable
attachment state as CI. Copy the single **lace-up** pattern in
[`AGENTS.md`](AGENTS.md) to enroll. See
[`docs/js-bazel-package.md`](docs/js-bazel-package.md) (`cache_backed`,
`substrate_mode`) for the consumer-facing details.

`spoke-ci.yml` exposes the **same opt-in, default-off** enrollment (TIN-2119)
via `cache_backed` + `substrate_mode` (and `cache_backed_targets` for the
SvelteKit flywheel-eligible CAS surface). When set, the `flywheel-build` and
`bazel-graph` jobs switch from `setup-nix@v2` (install-only) to `nix-setup@v2`
(which exports `BAZEL_REMOTE_CACHE` from cluster DNS — the spoke wiring fix),
export `GF_FLYWHEEL_PROFILE_STATE` from the manifest-driven substrate mode, run
the identical fail-closed contract, and execute a cache-backed Bazel build of
the flywheel-eligible targets reading the shared cache. The default path is
byte-identical for the ~34 non-opted spoke consumers. An opted spoke must also
set `flywheel_config: flywheel` so `flywheel-bazel` forwards the remote cache.

## Contributing

See [`RELEASING.md`](./RELEASING.md) for the release flow and SemVer
policy. Each PR must amend `## [Unreleased]` in `CHANGELOG.md`. Internal
composite-to-composite refs must use the current floating major tag, not
`@main` or an older major.

## Migration from `@main`

See [`docs/migration-v0-to-v1.md`](docs/migration-v0-to-v1.md) and
[`docs/migration-v1-to-v2.md`](docs/migration-v1-to-v2.md).
