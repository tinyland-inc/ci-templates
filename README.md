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
also include `tinyland.repo.json`, which is validated against the schema its own
`schema_version` names — `1` or `2`; see
[Manifest `schema_version` routing](#manifest-schema_version-routing).

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
| `secrets-scan` | TruffleHog + Gitleaks, both installed from checksum-pinned release archives (no Docker, no `curl \| sh`). See **Secrets-scan scanner pins** below. |
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

### Secrets-scan scanner pins

`secrets-scan` downloads each scanner as an exact release archive and verifies a
source-pinned SHA-256 before extraction. The restricted closure check
(`just restricted-workflow-contract-check`) asserts these defaults, so a bump is
a reviewed, two-file change.

| Scanner | Version input | Default | Archive |
|---|---|---|---|
| TruffleHog | `trufflehog-version` / `trufflehog-sha256` | `3.95.3` | `trufflehog_<v>_linux_amd64.tar.gz` |
| Gitleaks | `gitleaks-version` / `gitleaks-sha256` | `8.30.1` | `gitleaks_<v>_linux_x64.tar.gz` |

#### Gitleaks `[[allowlists]]` — spoke migration note (TIN-3900)

The pin was `8.21.2` through ci-templates `v2.14.0`. Gitleaks grew the plural
`[[allowlists]]` table in **8.25.0**; `8.21.x` parses a config containing it
without error and then **silently ignores every entry**. Every Tinyland
`.gitleaks.toml` (ci-templates, `site.scaffold`, and the spokes spawned from it)
uses `[[allowlists]]` exclusively, so none of those allowlists were in force in
CI — spokes were passing on the default ruleset alone, and any finding an
allowlist was meant to suppress had to be worked around with `.gitleaksignore`
fingerprints instead.

From `8.30.1` the allowlists apply. Two things spokes should check:

- **Do not mix singular and plural.** `8.30.x` **fails closed** on a config that
  declares both `[allowlist]` and `[[allowlists]]`:
  `Failed to load config error="[allowlist] is deprecated, it cannot be used
  alongside [[allowlists]]"`. Convert a lone `[allowlist]` to a single
  `[[allowlists]]` entry; never keep both.
- **Re-check `.gitleaksignore`.** Fingerprints added to work around allowlists
  that 8.21.2 was ignoring are now redundant. They are harmless, but prune them
  when the allowlist covers the same path so the ignore file keeps documenting
  only real, reviewed exceptions.

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
| `npm-publish.yml` | Pre-existing: Node package build + publish, callable only (no local tag/manual trigger). Ran GitHub-hosted until TIN-3914 moved all three jobs to `tinyland-nix`. |
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

### No GitHub-hosted runners (TIN-3914)

Operator ruling, 2026-08-19: *"we should NEVER have gh ubuntu runners in place
ever, we ONLY use GF infra cache fronted runners."* As of `v3.0.0` every
`runs-on` in this repository names a self-hosted org capability-class label.
There is no opt-out input — an estate-wide prohibition with a "keep using
hosted" knob would not be a prohibition — which is why this is a MAJOR release
rather than a default-off addition (`AGENTS.md` rule 2). Consumers are
unaffected until they bump their pin; the full mechanical migration, the
capacity numbers, and the explicit MAJOR-vs-MINOR argument are in
[`docs/migration-v2-to-v3.md`](docs/migration-v2-to-v3.md).

What moved:

| Workflow | Job(s) | Before | After |
|---|---|---|---|
| `spoke-ci.yml` | `secrets-scan`, `lanes-load`, `repo-manifest` | `ubuntu-latest` | `default_runner_class`, group-routed on opt-in |
| `spoke-lane-env.yml` *(deprecated)* | `check-blahaj-token`, `lanes-load`, `dispatch-apply`, `destroy-lanes` | `ubuntu-latest` | `tinyland-nix` |
| `js-bazel-package.yml` | `resolve-runner` | `ubuntu-latest` | `tinyland-nix` |
| `npm-publish.yml` | `build-and-test`, `publish-gpr`, `publish-npm` | `ubuntu-latest` | `tinyland-nix` |
| `rust-bazel-application.yml` | `trust-gate` | `ubuntu-24.04` | `tinyland-nix` |
| `spoke-deploy-cloudflare-pages.yml` | `build` | `ubuntu-latest` | `tinyland-nix` |
| `spoke-public-preview.yml` | `dispatch` | `ubuntu-latest` | `tinyland-nix` |

Two `js-bazel-package.yml` input **values** are retired and now rejected with a
migration error rather than silently re-routed: `runner_mode: hosted` and
`publish_mode: hosted_exception`. Retiring the publish exception has one
consequence worth reading before you bump: publishes are now always self-hosted,
and the pre-existing provenance guard only requests `npm publish --provenance`
off self-hosted runners, so **npm provenance is no longer requested** and
`npm_publish_provenance` is inert (the job says so with a `::warning::`).

`scripts/lint-runs-on.rb` enforces the rule at author time. A GitHub-hosted
label is a **FAIL**, not a warning, wherever it can be read statically: a bare
scalar, any element of a label array, a literal arm of a `${{ … }}` ternary, a
`fromJSON(vars.X || '[…]')` fallback array, a resolved `matrix` value, and
either arm of a static or runtime-composed `{group, labels}` mapping. The
previously-blessed "graceful degradation to hosted when cluster labels are not
reachable" fromJSON shape is now a failure — there is nothing left to degrade
to. An expression that resolves only *some* of its arms — one good literal plus an
opaque `vars.*` fallback — is floored at **WARN** rather than passing: the audit
is incomplete, and that shape is the easy one to write. It is not a FAIL,
because this guard's core promise is that it never fails a `runs-on` it cannot
statically resolve.

Third-party managed fleets (`blacksmith-*`, `depot-*`, `namespace-profile-*`, …)
are neither GitHub's infrastructure nor GF cache-fronted, and the ruling named
GitHub runners: they **WARN**, surfacing for a deliberate decision instead of
passing silently. Both gates agree on that — `just no-hosted-runners-check` is
label-aware and case-insensitive, so `blacksmith-4vcpu-ubuntu-2204` and
`namespace-profile-default` get the same verdict. Its predecessor was a
substring grep, which failed the first (it embeds `ubuntu-2`) and passed the
second, and let `Ubuntu-Latest` through entirely — an effective policy decided
by spelling.

| Gate | Reads | Catches |
|---|---|---|
| `just lint-runs-on-check` | `runs-on` values, structurally | the routing itself; 75-case oracle, this repo dogfoods at 0 FAIL |
| `just no-hosted-runners-check` | every schedulable surface, textually | a label hiding in an input default, a `fromJSON` fallback, an env value, or a JSON schema |
| `just lanes-schema-runner-class-check` | what the lanes schema *admits*, semantically | a hosted label that is representable as consumer data even when never written down |

All are in `just check`, each with its own self-test.

`.github/actionlint.yaml` declares the six capability labels so actionlint stops
reporting them as unknown. It is a declaration, not a suppression: a typo'd or
repo-shaped label still reports, and `scripts/lint-runs-on.rb` remains the
authority on which labels are admissible.

### The repo-role census on `spoke-ci.yml` (opt-in `allowed_repo_roles`)

`spoke-ci.yml`'s `repo-manifest` job asserts that the calling repo's
`taxonomy.primary_role` is one this template is for. Until `v3.1.0` that
allowlist was hardcoded — **at two independent sites**: the `repo-manifest` job
and, again, the `cache_backed` lane's manifest gate inside `flywheel-build`. A
spoke could satisfy one and fail the other, and a fix to either would have
looked complete. `allowed_repo_roles` replaces both, and the matching pair in
`spoke-ci-restricted.yml`.

```yaml
    with:
      # comma-separated or a JSON array — both normalize identically
      allowed_repo_roles: static-spoke,static-spoke-scaffold,app-stateful-spoke
```

- **Both spellings work at the ref you pin.** The JSON→comma normalization is
  done by the workflow (`startsWith`/`fromJSON`/`join`), not by the composite
  action. That placement is the point: a `uses:` step resolves the action at
  *its own* ref, so a rule written action-side only reaches you once a release
  moves that ref — and never, for the restricted variant, whose closure is
  pinned to an exact release by contract. The workflow file is the thing you
  pin, so the rule ships with the version you name.
- **Default `"static-spoke,static-spoke-scaffold"` = today's exact literal.**
  Every consumer that does not opt in renders byte-identically (`AGENTS.md`
  rule 2), proved site by site — and the site *count* pinned — by
  `just repo-role-census-contract-check`.
- **`app-stateful-spoke` is ratified but not defaulted.** It is in the vendored
  schema's `$defs.repoRole`, so it is a valid role; it is not in this default,
  because ratifying a role is not ratifying a template binding. The schema's own
  `allOf` block constrains `static-spoke`/`static-spoke-scaffold` to
  `owns_runtime_backend`/`owns_auth`/`owns_payments`/… `== false` and
  deliberately omits `app-stateful-spoke` — the families are materially
  different, and this census is the only place in ci-templates where
  `primary_role` is enforced at all. Opting in is one line; widening the default
  for ~190 consumers would be a MAJOR to undo. Full argument in the `v3.1.0`
  CHANGELOG entry.
- **A census failure names its remedy** — the error prints the exact
  `allowed_repo_roles:` line that would admit the rejected role. This one *is*
  action-side, so it reaches `spoke-ci.yml` consumers from `v3.1.0` (its
  internal action refs now track `@v3`); the restricted variant will show it
  when its pinned closure is next advanced.

**GFTB spokes: one edit covers all three.** A Great-Falls-Tool-Bus spoke moving
to a private runner group, an org capability class, and a non-static role does
it in a single `with:` block plus the pin bump:

```yaml
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v3.1.0
    with:
      default_runner_class: great-falls-tool-bus-nix
      heavy_runner_class: great-falls-tool-bus-nix
      kvm_runner_class: great-falls-tool-bus-nix
      runner_group: great-falls-tool-bus-infra
      allowed_repo_roles: static-spoke,static-spoke-scaffold,app-stateful-spoke
    secrets: inherit
```

### Owner-scoped runner groups on `spoke-ci.yml` (opt-in `runner_group`)

`spoke-ci.yml` takes an optional `runner_group` input. **Default `""` = today's
label-only routing**, byte-identical for every non-opted consumer. Set it and
each self-hosted job routes with GitHub's structured form instead:

```yaml
jobs:
  ci:
    # Pin the exact release that carries `runner_group`: the input does not
    # exist in v2.14.0 or earlier; it ships in v3.0.0. Bumping the pin is
    # REQUIRED alongside the input — a caller that adds `runner_group:` while
    # pinned to an older release fails at workflow start with an unknown input.
    # v3.0.0 also retires GitHub-hosted runners; read docs/migration-v2-to-v3.md
    # before bumping.
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v3.0.0
    with:
      default_runner_class: tinyland-nix
      heavy_runner_class: tinyland-nix
      kvm_runner_class: tinyland-nix
      runner_group: great-falls-tool-bus-infra   # <- the only new line
    secrets: inherit
```

| Job | `runner_group` unset | `runner_group` set |
|---|---|---|
| `secrets-scan`, `lanes-load`, `repo-manifest` | `default_runner_class` | `{ group: <runner_group>, labels: default_runner_class }` |
| `flywheel-build`, `flywheel-test` | `runner_labels_json` → `matrix.lane.runner_class` → `default_runner_class` | `{ group: <runner_group>, labels: <same value> }` |
| `bazel-graph` | `heavy_runner_class` | `{ group: <runner_group>, labels: heavy_runner_class }` |
| `playwright` | `kvm_runner_class` | `{ group: <runner_group>, labels: kvm_runner_class }` |

- **Label resolution is untouched.** The group mapping carries the *same* value
  the job resolves today, including the string-vs-array shape of
  `runner_labels_json`. The input adds a group; it never re-picks a label.
- **The hosted class is gone, and the group now covers everything.** TIN-3914
  moved `secrets-scan`, `lanes-load`, and `repo-manifest` off `ubuntu-latest`
  onto `default_runner_class`, so all seven jobs are group-routed on opt-in.
  The gate still *derives* the never-group-routed set from "literal `runs-on`
  in the pinned baseline" rather than naming jobs, so that class is currently
  empty and a future literal-`runs-on` job lands on an already-tested rule; the
  self-test keeps that branch executable against a synthetic baseline.
- **A group narrows, it does not widen.** GitHub schedules onto a runner that is
  in that group **and** carries the labels. A group whose runners lack the
  capability label queues forever — which is why this is opt-in per spoke.
- **Workflow source is not proof.** The org-level group must already exist, have
  the calling repository in its selection, and serve the capability label. The
  runs-on linter rejects generic groups (`Default`, `shared*`, GitHub-hosted)
  and any GitHub-hosted label in either arm of the mapping.
- **This is routing, not trust.** It does not add the fork/pre-scheduling trust
  gate; a private repo that needs a fail-closed group+capability contract still
  uses `spoke-ci-restricted.yml`, where `runner_group` is *required*.
- YAML cannot express a conditional mapping, so the workflow composes the
  mapping at runtime via `fromJSON(format(...))`. `just runner-group-contract-check`
  renders both paths over a scenario grid and fails if the default path ever
  stops being byte-identical.

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

`schemas/tinyland-repo-manifest.schema.json`,
`schemas/tinyland-repo-manifest.v2.schema.json`, and `schemas/lanes.schema.json`
are vendored from `tinyland-inc/site.scaffold/docs/schemas/`. The
schema-doc repo is the source of truth; this repo vendors at known
stable paths so composite actions can `jsonschema` against them.

### Manifest `schema_version` routing

`tinyland.repo.json` carries an integer `schema_version`, and each published
value has its own vendored schema: `1` →
[`schemas/tinyland-repo-manifest.schema.json`](./schemas/tinyland-repo-manifest.schema.json),
`2` →
[`schemas/tinyland-repo-manifest.v2.schema.json`](./schemas/tinyland-repo-manifest.v2.schema.json).

`SCHEMA_BY_VERSION` in
[`scripts/manifest-schema-validate.py`](./scripts/manifest-schema-validate.py) is
the only place that mapping lives. The `repo-manifest-validate` composite passes
`--schemas-dir schemas` and lets the validator route; it does not name a schema
file. `validate-ci-templates.py cache-backed-optin-contract` fails if the action
starts resolving one itself, or if a mapped version has no vendored schema.

The mapping is **total**. A `schema_version` that is absent, denotes no integer,
or is an integer with no vendored schema exits `3` and names the value it saw;
it is never routed to v1 as a fallback. "Denotes an integer" is JSON's
definition, not Python's: `2.0` routes to v2, because JSON Schema 2020-12 counts
a number with zero fractional part as an `integer` and the v2 schema's
`{"const": 2}` accepts it — a router that exited `3` there would be refusing to
route a document the schema it would have routed to accepts. `true` does *not*
route to v1, even though `bool` subclasses `int` in Python. Both rules live in
`_as_schema_version()`. Before this routing existed, the composite
hardcoded the v1 path, so a consumer on the published `schema_version` 2 failed
the gate with a wall of `Additional properties are not allowed` ending in `at
/schema_version: 1 was expected` — the gate blaming the manifest for a branch
the gate did not have. Exit `4` is separate again, for a version that routes to
a schema absent from the ci-templates checkout: that means nothing validated the
manifest, which is a broken release rather than a consumer problem.

### One engine, or no verdict

The validator imports `jsonschema` or exits `2` naming the dependency. There is
no fallback, deliberately (TIN-4132/TIN-4192).

A dependency-free stdlib validator used to stand in whenever the package was
unimportable. It implemented a *subset* of JSON Schema and, for months, never
evaluated `not` — so every prohibition passed unconditionally. The v2 schema
expresses its role discipline negatively (`not` ×17, `contains` ×13, `anyOf`
×4), so under the subset the overlay branches were unsatisfiable, which was
misread as schema over-reach for weeks. Widening it and adding a coverage guard
made it *honest about its gaps*; it was still a second engine kept in step with
the first by a hand-written harness. A gate that reads as coverage while
enforcing less than the schema says is worse than no gate.

Its reason for existing is gone as well. It guarded a cold `nix develop`
failing on a nix-store lock (TIN-2109) — a failure class of the shared-store
host-runner generation. Current ARC pods mount per-pod ephemeral nix stores, so
that contention is structurally gone. **`jsonschema` is supplied by the
`nix-setup` composite**, cache-hot from the in-cluster Attic; run it in the job
before `repo-manifest-validate`. The composite does *not* shell out to
`nix develop` itself — `just cache-backed-optin-contract-check` still asserts it
must not.

`scripts/manifest-schema-validate-selftest.sh` (via `just
manifest-validate-selftest`) covers routing and validation against that one
engine, plus a **refusal contract**: with `jsonschema` hidden behind an
`ImportError` shim, the validator must exit `2` and name the dependency, and
must not return a verdict of any kind — including on an *invalid* manifest,
where answering `1` would mean something still validated it. Every one of those
cases returned `0` or `1` off the subset before it was deleted, so they are live
guards against a fallback being reintroduced rather than tautologies. It also
carries an **engine-identity control**: a `dependentRequired` violation must be
*reported*, which is a verdict only the real engine can produce. On a host that
cannot import `jsonschema` the harness refuses (exit `2`) rather than printing
"0 failed" over an engine it never ran.

### Vendored schema provenance

`schemas/VENDORED.json` records the source revision and per-file sha256 of every
manifest schema vendored from site.scaffold, and `just
vendored-schema-provenance-check` asserts the copies still match. Before it,
there was no lock and no gate, and the v1 copy had silently diverged from its
source in **both** directions with nothing comparing them.

The gate is deliberately **hermetic**: recorded digests only, no network. A
network call would make every consumer's CI depend on another repository being
reachable. It catches what a lock can catch offline — a hand-edit that never
went through a re-vendor — plus a vendored manifest schema that no entry records
and a record with no entries at all. Upstream *freshness* is a separate,
non-blocking question. An entry marked `drifted` is reported, never failed.

**Known drift, not closed here:** the vendored
`tinyland-repo-manifest.schema.json` (v1) and site.scaffold's copy have diverged
in both directions. Measured by normalising both documents before diffing, so
indentation and key order cannot inflate the count (a raw `diff -u` of the two
files reports 136 changed lines, almost all of it formatting):

```console
$ norm() { python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])),indent=2,sort_keys=True))' "$1"; }
$ diff <(norm ../site.scaffold/docs/schemas/tinyland-repo-manifest.schema.json) \
       <(norm schemas/tinyland-repo-manifest.schema.json) | grep -c '^[<>]'
22
```

22 differing lines (13 only upstream, 9 only here), which resolve to **two
constraint-bearing differences, one in each direction** — this repo carries an
`authorities.artifact_registry` property site.scaffold lacks; site.scaffold
carries an `authorities` `not`/`required: [gitops_receiver]` constraint this copy
lacks — plus **five annotation-only differences** (four reworded `description`s
and one `description` dropped from a `$ref`). Pinned to blobs so the figure stays
checkable: this copy is `c724d1bf`, site.scaffold's is `981427d8` at
`site.scaffold` `6c58bb6`. Nothing compares them automatically. The v2 schema
vendored alongside is byte-identical to site.scaffold's (both blob
`74c13a7a`, last changed there by `8659dcd`), and reconciling the v1 copies is a
separate change to the vendored file, not to this router.

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
