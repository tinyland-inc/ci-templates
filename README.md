# ci-templates

Reusable GitHub Actions composite actions + reusable workflows for the
Tinyland CI house style.

> ⚠️ **Pin to an immutable release tag such as `@v2.0.0`.** `@main` is the develop branch and
> may break without notice. See [`RELEASING.md`](./RELEASING.md) for the
> SemVer contract.

> **Superseded (2026-08-05):** the blahaj receiver path was evicted
> (blahaj #1255); lane lifecycle belongs to the app owner overlay — see
> site.scaffold `docs/patterns/owner-overlay-apply-plane.md` and the merged
> scaffold #119 recut (2026-08-06, `8862f359`). The `lane-dispatch` /
> `lane-reap` / `public-preview-dispatch` actions and the
> `spoke-lane-env*` / `spoke-public-preview`
> workflows below document the retired-era receiver contract as released
> (spokes pin immutable tags, so released behavior is unchanged), but
> `tinyland-inc/blahaj` no longer hosts the receivers. Do not wire new
> spokes at blahaj; the behavior recut ships via the versioned release
> train. The zero-caller TTL half (`lane-ttl-reap` action,
> `spoke-lane-ttl-reap.yml`, `schemas/lane-ttl-reap-dispatch.schema.json`)
> was removed from `main` on 2026-08-07 (TIN-489); released tags retain it.

Spokes spawned from `tinyland-inc/site.scaffold` consume this repo for:

- **Spoke CI** (lint, type-check, build, test, Bazel graph, optional
  Playwright) via `spoke-ci.yml` reusable workflow.
- **Per-PR ephemeral env lifecycle** (build image, dispatch to the
  retired-era Blahaj receiver, reap on close) via `spoke-lane-env.yml`.
- **Static projection snapshot refresh** via `spoke-pulse-ingest.yml`.
- **GloriousFlywheel REAPI binding** via the `flywheel-bazel` composite
  action.
- **Scaffold AX/skills inheritance** via `inherit-scaffold-skills`, which
  pulls `plugins/scaffold-core` from `tinyland-inc/site.scaffold` at a pinned
  tag.
- **Repo-shape manifest validation** via `repo-manifest-validate`.
- **Schema-validated `lanes.json` loading** via `lanes-load`.
- **Blahaj `repository_dispatch` payload construction** via
  `lane-dispatch` / `lane-reap` (retired-era receiver — see Superseded
  note above).
- **Public client preview dispatch** via `public-preview-dispatch`;
  the retired-era Blahaj receiver owned Cloudflare DNS, Access, Tunnel
  ingress, and cleanup — that ownership now sits with the app owner
  overlay.
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

**Deprecated** — `spoke-lane-env.yml` below is the retired-era
Blahaj-dispatch PR-env path, kept callable only. A new spoke wires its own
owner-overlay PR-env create+destroy+TTL workflow per site.scaffold
`docs/patterns/owner-overlay-apply-plane.md`, not this template:

```yaml
# .github/workflows/lane-env.yml (deprecated shape, do not copy for new spokes)
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
validates `tinyland.repo.json`, verifies internal action refs resolve to
checked-in sibling actions, recursively proves the restricted workflows' exact
self/third-party dependency closure, asserts `bazelrc/flywheel.bazelrc` and
`bazelrc/ci-cached.bazelrc` remain endpoint-free, asserts the `cache_backed`
opt-in lane stays default-off and cache-first, guards the finite/native contract
of `rust-bazel-application.yml`, and runs the canonical Tinyland gitleaks
working-tree scan.

## Composite actions

| Action | Purpose |
|---|---|
| `nix-setup` | Configure Nix + cache hints. Does not invent Bazel endpoints. Opt-in `attic-public-read: true` degrades to a tokenless, read-only public Attic substituter — see below. |
| `nix-build` | Run `nix build` with Attic binary cache. |
| `greedy-cache` | Start Attic `watch-store` daemon for concurrent push. |
| `secrets-scan` | TruffleHog + Gitleaks. |
| **`inherit-scaffold-skills`** | Pull `plugins/scaffold-core` from `site.scaffold` at a pinned ref and materialize `.agents/skills` + `.claude/skills`. |
| **`repo-manifest-validate`** | Validate `tinyland.repo.json` and optionally require repo roles such as `static-spoke`. |
| **`cache-attachment-validate`** | Execute the release-vendored cache attachment contract without a network source fallback. |
| **`flywheel-bazel`** | `bazelisk` wrapper with endpoint-free `--config=flywheel[-executor]`. Supplies cache/executor endpoints from runtime env or inputs. Refuses executor on non-cluster runners. |
| **`lanes-load`** | Validate + load `.github/lanes.json`. Outputs matrix-ready `lanes_json`. |
| **`lane-dispatch`** *(deprecated)* | Emit Blahaj `<spoke>-lane-env` provision payload. Supports `dry_run`. PR-env create is an owner-overlay capability now; see the Superseded note above. |
| **`lane-reap`** *(deprecated)* | Emit Blahaj destroy payload. Idempotent. PR-env destroy is an owner-overlay capability now. |
| **`public-preview-dispatch`** *(deprecated)* | Emit Blahaj public/client preview payload with Cloudflare Access allowlist. The owner overlay is the preview producer now. |
| **`flywheel-reapi-proof`** | Dispatch and optionally await a GloriousFlywheel executor-backed proof run, correlated by a unique request id. |
| **`lane-status-check`** | Post per-lane `ci/lane/<name>` GitHub commit status. |
| **`pulse-ingest-validate`** | Validate a Pulse / static projection snapshot. |
| **`rust-bazel-preflight`** | Validate the complete native matrix, owner-group route, and finite target arrays before any dynamic runner is scheduled or caller source is checked out. |
| **`rust-bazel-binary-custody`** | Validate the operator-projected, root-owned raw Bazelisk Nix-store path before caller checkout; never use caller input or PATH to select Bazelisk. |
| **`rust-bazel-contract`** | Fail-closed lane validation for native platform identity, tracked Bazel 9 pin/Bzlmod lock, finite exact targets, and protected-ref cache-write admission. No build, endpoint, credential, or publication authority. |

See per-action `action.yml` files for full input/output documentation.

### Attic tokenless read degrade (opt-in)

`nix-setup`, `nix-build`, and `greedy-cache` accept an `attic-public-read`
input, **default `"false"`**. With it left at its default, behavior is
byte-identical to before this feature existed: no fallback endpoint, no
extra `nix.conf` writes, no new env exports — rule 2 of `AGENTS.md`.

Set `attic-public-read: "true"` on any of the three to opt in. What flips:

- If no `attic-server` input and no auto-detected `ATTIC_SERVER`
  (self-hosted org overlay / fleet env) resolves anything, `nix-setup` falls
  back to the tinyland-inc public-read `main` cache
  (`https://nix-cache.tinyland.dev`,
  `main:eaUydxuDu7xBoy5cCo3MdknYAkVyTIASQ7DGuwxa+XA=`) and configures it as
  an **anonymous, tokenless, read-only** Nix substituter. This fallback
  **never exports `ATTIC_SERVER`** into the job environment — `nix-build`'s
  push step is gated on `env.ATTIC_SERVER != '' && env.ATTIC_TOKEN != ''`,
  so a spoke that happens to have `ATTIC_TOKEN` set but never configured a
  push destination cannot be silently flipped into pushing.
- If an explicit/auto-detected `attic-server` DID resolve to a real
  (tenant) cache, the same opt-in also wires up a read-only substituter for
  *that* server, but only when the caller explicitly supplies
  `attic-public-key` for it (or a token is already in scope, in which case
  the authenticated path — `attic-action` login in `nix-build`, or
  `greedy-cache`'s own tiered substituter step — already establishes trust
  and this is skipped to avoid duplicate `nix.conf` lines). The
  tinyland-inc key is **never** baked in for an arbitrary/tenant server —
  only for the tinyland-inc public default itself. Precedence for the
  trusted key is: `attic-public-key` input, then an `ATTIC_PUBLIC_KEY`
  already exported in the runner environment, then — only for the
  tinyland-inc default — the baked key.
- `ATTIC_TOKEN` continues to gate the authenticated/push half exactly as
  before, in `nix-build` and `greedy-cache`: **present and valid** is
  unchanged (`nix-build` runs `ryanccn/attic-action` to log in and push;
  `greedy-cache` logs in and starts the `watch-store` push daemon).
  **Absent**, with `attic-public-read: "true"` and a read-only substituter
  actually configured, both actions emit a loud
  `::warning::Attic token absent — anonymous public read only, pushes
  disabled` instead of a hard failure or a silent no-op (skipped if the
  caller explicitly passed `push-cache: false`, since there's no degrade to
  warn about). Absent, with `attic-public-read` left at its default
  `"false"`, behavior is unchanged: no substituter, no warning beyond the
  pre-existing "Attic not configured" notice.

## Reusable workflows

| Workflow | Purpose |
|---|---|
| `js-bazel-package.yml` | Pre-existing: JS/TS packages built by Bazel and published to GitHub Packages, with npmjs required/optional/disabled by package policy. Supports an **opt-in, default-off `cache_backed`** shared-cache Bazel validation lane (cache-first; see below). |
| `npm-publish.yml` | Pre-existing: hosted-only Node package build + publish, callable only (no local tag/manual trigger). |
| **`rust-bazel-application.yml`** | Opt-in/default-off native Darwin/Linux Rust application validation with Bazel-only rustfmt, clippy, build, unit, integration, and package targets; cache reads are runtime-attached and writes require an explicitly enabled protected push ref. |
| **`spoke-ci.yml`** | Canonical spoke CI: secrets-scan, lanes-load, per-lane flywheel-bazel build/test, bazel-graph, optional Playwright. |
| **`spoke-lane-env.yml`** *(deprecated)* | Retired-era Blahaj-dispatch PR-env workflow, kept callable only. The PR-env producer is the product's owner-overlay repository — see site.scaffold `docs/patterns/owner-overlay-apply-plane.md` and the merged scaffold #119 recut. Do not point a new spoke at it. |
| **`spoke-ci-restricted.yml`** | Explicit private-repo opt-in variant of `spoke-ci.yml`; every job requires an owner `-infra` runner group plus its reviewed capability label. |
| **`spoke-lane-env-restricted.yml`** *(deprecated)* | Explicit private-repo opt-in variant of `spoke-lane-env.yml`; preserves lane semantics while requiring group+capability routing and rejecting fork execution before checkout. Same PR-env producer deprecation applies. |
| **`spoke-public-preview.yml`** *(deprecated)* | Reusable public/client preview dispatcher for Cloudflare Access-gated aliases. The owner overlay is the preview producer now. |
| **`spoke-pulse-ingest.yml`** | Snapshot-refresh PR opener. |
| **`spoke-deploy-cloudflare-pages.yml`** | Sanctioned **opt-in** Cloudflare Pages deploy lane. Builds the adapter-static `build/` via `nix develop --command just setup/check/build`, then `wrangler pages deploy build`. Credential-skips when the org CF secrets are absent; PR events build only. Does **not** replace the scaffold default GitHub-Pages lane. |

The restricted variants are a separate, default-off source surface. Their
`v2.12.1` release closes the transitive graph with exact self-release refs,
full third-party commit SHAs, and checksum-verified scanner archives. Existing
`spoke-ci.yml` and `spoke-lane-env.yml` callers do not enter a private runner
group by upgrading their pin. Adoption is deliberately sequenced: the owner
`-infra` overlay first creates or adopts the selected private group and proves
its repository selection; ci-templates then publishes an immutable release;
finally the private app repo pins that release and passes the exact group plus
capability inputs. Workflow source is not proof that the runner group exists,
has the intended repository selection, or has live capacity. See
[`docs/restricted-private-runners.md`](docs/restricted-private-runners.md).
This release admits only the reviewed `tinyland-infra` group and exact Tinyland
capability values; adding another owner group requires a reviewed source change
and immutable release, not a caller-selected fallback.

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
    permissions:
      contents: read
      deployments: write
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-deploy-cloudflare-pages.yml@v2.10.0
    # Pass the CF secrets EXPLICITLY. `secrets: inherit` does not reliably
    # deliver repo secrets when the calling repo lives in a DIFFERENT org than
    # ci-templates (observed 2026-07-04: Great-Falls-Tool-Bus spoke built green
    # while the deploy step credential-skipped on every push). Explicit mapping
    # works in both same-org and cross-org callers.
    secrets:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

`project_name` defaults to the slugified repository name (dots/underscores →
hyphens); override it with the `project_name` input when the CF project name
differs. The deploy step **skips with a `::notice::`** when
`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` are absent, so the wrapper
merges safely before the org token is minted (personal-account spokes never
hold CF creds). Use `secrets: inherit` so org/repo-provisioned secrets are
available by name without forcing absent optional secrets to exist. Do **not**
copy a `cloudflare-pages-${{ github.ref }}` concurrency group into the caller:
the reusable workflow already owns that group, and duplicating it deadlocks the
caller against the called `deploy` job. PR events build only — they never deploy
and never mutate repo state. Pin `@vX.Y.Z` to your intended release; the example
above assumes the first release that ships this lane.

## Schemas

`schemas/tinyland-repo-manifest.schema.json` and `schemas/lanes.schema.json`
are vendored from `tinyland-inc/site.scaffold/docs/schemas/`. The
schema-doc repo is the source of truth; this repo vendors at known
stable paths so composite actions can `jsonschema` against them.

`schemas/blahaj-dispatch.schema.json` and
`schemas/public-preview-dispatch.schema.json` are retired-era historical
artifacts: the merged scaffold #119 recut deleted their upstream sources
from `site.scaffold/docs/schemas/`, so they no longer have a source of
truth there. The vendored copies remain only because the deprecated
Blahaj-dispatch composites above still validate against them; do not
treat them as current contract surface.
(`schemas/lane-ttl-reap-dispatch.schema.json` was removed with the
`lane-ttl-reap` composite, its only consumer, on 2026-08-07.)

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
declared-vs-actual mismatch fails closed), rejects hosted / non-cluster runner
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

## Native Rust+Bazel applications

`rust-bazel-application.yml` is a separate opt-in/default-off workflow for
Bazel-authoritative Rust applications. It takes an exact caller-owned native
Darwin/Linux matrix, owner-overlay runner group, and finite target arrays. A
hosted, no-checkout/no-secret admission job rejects public, fork, and
`pull_request_target` events before any private native runner is assigned.
Each admitted runner must project one immutable raw Bazelisk Nix-store path;
the workflow validates it before checkout and never executes PATH Bazelisk.
Pull-request cache use receives only a distinct server-enforced read
credential. A write credential is materialized only after a caller opts in and
GitHub marks the pushed main branch or release tag protected; remote execution
is always disabled. See
[`docs/rust-bazel-application.md`](docs/rust-bazel-application.md).

## Contributing

See [`RELEASING.md`](./RELEASING.md) for the release flow and SemVer
policy. Each PR must amend `## [Unreleased]` in `CHANGELOG.md`. Restricted
workflow self-references must use an exact immutable release and all
third-party Actions in that closure must use full commit SHAs; `@main` and the
floating major are rejected by the closure validator.

## Migration from `@main`

See [`docs/migration-v0-to-v1.md`](docs/migration-v0-to-v1.md) and
[`docs/migration-v1-to-v2.md`](docs/migration-v1-to-v2.md). Note the v0→v1
guide recommends `spoke-lane-env.yml`; that recommendation is superseded by
the Superseded note at the top of this README.
