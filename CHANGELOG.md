# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer 2.0](https://semver.org/).

## [Unreleased]

### Changed

- **`js-bazel-package.yml` npmjs policy is explicit** — adds
  `npm_publish_mode=required|optional|disabled`. The default remains
  `required` for existing consumers, while Bazel-first packages can make
  npmjs best-effort or disabled when GitHub Packages and the Tinyland Bazel
  registry are the release authority.
- **`js-bazel-package.yml` shared runner labels are guarded** —
  `runner_mode=shared` now rejects an explicitly empty
  `shared_runner_labels_json`, catching missing caller repo variables before the
  workflow silently falls back to the default shared runner class.

## [2.0.0] — 2026-05-20

### Added

- **`inherit-scaffold-skills` composite** — pulls
  `plugins/scaffold-core` from `tinyland-inc/site.scaffold` at a pinned tag or
  commit SHA, dereferences skill symlinks, and can materialize
  `.agents/skills` plus `.claude/skills` in consumer spokes. Branch refs such
  as `main` are rejected by default so inherited AX contracts do not drift
  silently.
- **v1 to v2 migration guide** — documents endpoint-free Flywheel behavior,
  scaffold skills inheritance, v2 internal refs, and rollback posture.
- **`public-preview-dispatch` composite + `spoke-public-preview.yml`** —
  reusable dispatch path for explicit public/client review aliases. The payload
  is schema-validated and carries source repo, PR, commit, lane, origin host,
  preview hostname, TTL, and Cloudflare Access allowlist. Spokes request the
  alias; Blahaj owns DNS, Access, Tunnel ingress, and cleanup.
- **`lane-ttl-reap` composite + `spoke-lane-ttl-reap.yml`** — reusable
  scheduled TTL backstop dispatcher. Blahaj owns listing and idempotent
  destruction of expired lane environments.
- **`flywheel-reapi-proof` composite** — reusable dispatcher for
  GloriousFlywheel executor-backed proof workflows. The composite does not
  promote target classes by itself; GF proof artifacts remain authoritative.
- **Public preview and TTL reap schemas** — vendored from the site.scaffold
  contract alongside the existing lane schemas.
- **`repo-manifest-validate` composite + repo manifest schema** — reusable
  validation for `tinyland.repo.json`, including optional role gating such as
  `static-spoke,static-spoke-scaffold`.
- **Repo-local validation contract** — adds `Justfile`, `flake.nix`, and
  `tinyland.repo.json` so this template repo can validate itself the same way
  consuming repos do. `just check` now parses workflow/action YAML, parses
  vendored schemas, validates the repo manifest, checks v2 internal refs, and
  enforces endpoint-free Flywheel defaults plus the canonical Tinyland gitleaks
  working-tree scan.

### Changed

- **Flywheel Bazel binding is endpoint-free** — `bazelrc/flywheel.bazelrc`
  no longer hard-codes `remote_cache`, `remote_executor`, or cache upload
  authority. `flywheel-bazel` now passes `--remote_cache` and
  `--remote_executor` from runtime env/action inputs and fails fast when the
  required endpoint is absent.
- **Reusable workflow internal refs target v2** — v2 workflows and nested
  composites call sibling ci-templates actions through `@v2`, not `@v1`, so a
  `spoke-ci.yml@v2.0.0` consumer receives the endpoint-free Flywheel and
  manifest-validation behavior from the same major release.
- **Internal action refs no longer use `@main`** — nested ci-templates action
  calls now use the current floating major tag, and consumer docs point at
  immutable release tags.
- **Schema validators can fall back to the consumer Nix dev shell** —
  `lanes-load` and `repo-manifest-validate` use host Python when `jsonschema`
  is available and otherwise route through `nix develop --command python3`.
- **`spoke-ci.yml` now validates repo manifests when present** — pre-manifest
  consumers continue with a notice; repos that ship `tinyland.repo.json` must
  declare `static-spoke` or `static-spoke-scaffold` for the spoke workflow.
- **Release PRs may carry an empty Unreleased section** — `release: vX.Y.Z`
  PRs are allowed through the changelog gate when branch protection blocks the
  workflow-driven direct push release path.

### Fixed (v1.1.5)

- **`lane-status-check` composite — use `curl` instead of `gh api`** —
  the action posted per-lane commit statuses via `gh api`, which
  requires the GitHub CLI on the host PATH. On runners where `gh`
  only lives inside the spoke flake's devShell, the call failed with
  `gh: command not found` (exit 127) and turned successful builds
  into fake job failures. Surfaced by darkmap PR #86 / TIN-1414 —
  the `flywheel-build` step's underlying `bazelisk build` succeeded
  (`state: "success"` payload was even emitted), but the `gh api`
  POST that followed killed the job.
  Fix: replaced `gh api` with `curl -X POST` calling the same
  `/repos/{owner}/{repo}/statuses/{sha}` endpoint directly. `curl`
  is ubiquitous on Linux runners and doesn't need a flake devShell.
  Also bumped the `lane-status-check@v1.0.0` pin in `spoke-ci.yml`
  to `@v1.1.5`.

### Fixed (v1.1.4)

- **`flywheel-bazel` composite — route bazelisk through `nix develop`
  when not on host PATH** — the action invoked `bazelisk` directly,
  assuming it lives on the runner's system PATH. On runners that
  declare bazelisk inside the spoke flake's devShell (the Tinyland
  default — every spoke flake adds `bazelisk` to `buildInputs`), the
  bare invocation failed with `bazelisk: command not found` in ~1
  second. Surfaced by darkmap PR #86 / TIN-1407.
  Fix: probe `command -v bazelisk`; if found, invoke directly
  (backward-compatible for runner images that preinstall bazelisk
  system-wide). If absent and `flake.nix` is present, route the call
  via `nix develop --command bazelisk ...`. If neither path is
  available, fail loudly with a clear error.
  Also bumped the `flywheel-bazel@v1.0.0` pin in `spoke-ci.yml` to
  `@v1.1.4` so the wrapper workflow picks up the new behavior.

### Fixed (v1.1.3)

- **`setup-nix` composite — ensure `nixbld` group/users + start the
  daemon if needed** — v1.1.2 introduced `setup-nix` but only handled
  install/detect/feature-flags. On Tinyland self-hosted runners the
  daemon socket wasn't reachable, so `nix develop` fell back to direct
  DB access and the runner user got `error: opening lock file "/nix/var/nix/db/big-lock": Permission denied`.
  Surfaced by darkmap PR #86 (the symptom that v1.1.2 was supposed to
  fix re-appeared at the next step).
  Fix: added the missing pair of steps from
  `GloriousFlywheel/.github/actions/nix-job`:
    1. Create the `nixbld` group and `nixbld1..nixbld32` build users if
       absent (multi-user nix prerequisite).
    2. `nix store ping`; if it fails, `sudo -b $(command -v determinate-nixd) daemon`
       (or `nix-daemon --daemon` as fallback) and wait up to 15 s for
       the socket to come up.
  No behavior change for callers — same workflow inputs, same actions
  block in spoke-ci.yml + spoke-lane-env.yml. Ships as v1.1.3.

### Added

- **`.github/actions/setup-nix/action.yml`** — new composite action that
  detects an existing Nix installation (probes
  `/nix/var/nix/profiles/default/bin` + `$HOME/.nix-profile/bin`,
  then `command -v nix`). When Nix is preinstalled, adds it to PATH
  and writes a per-user `~/.config/nix/nix.conf` with the requested
  flags. When absent, falls through to
  `DeterminateSystems/determinate-nix-action@v3`. Replaces all 8 use
  sites of `cachix/install-nix-action@v31` in `spoke-ci.yml` (5) and
  `spoke-lane-env.yml` (3).

### Fixed

- **All cachix/install-nix-action call sites** — the cachix action
  aborts hard with `Aborting: Nix is already installed at /nix/var/nix/profiles/default/bin/nix`
  on self-hosted runners that have Nix preinstalled (the case for
  the Tinyland `tinyland-nix*` runner classes). Subsequent
  `nix develop` then failed with `error: opening lock file "/nix/var/nix/db/big-lock": Permission denied`
  because the runner user wasn't granted access to the daemon
  database that the preinstalled multi-user nix relied on.
  Surfaced by darkmap PR #86 / TIN-1402 (every flywheel-build and
  flywheel-test matrix job failed in ~9 seconds).
  Fix: route all callers through the new `setup-nix` composite,
  which handles both the preinstalled-nix case and the
  no-nix-installed case uniformly.

### Fixed

- **`spoke-ci.yml` — strip literal `${{ ... }}` expressions from
  `inputs.runner_labels_json.description`** — GitHub evaluates
  `${{...}}` inside workflow-level `description:` text at PARSE time
  and rejects expressions that reference contexts not available there
  (`vars`, `secrets`, etc.). v1.1.0 shipped two example expressions
  inside the description, which caused every caller to fail in 0
  seconds with no jobs created. Replaced the embedded expressions with
  plain-text guidance pointing to the README / release notes.
- **`spoke-lane-env.yml` — remove invalid `if-skip:` job key on
  `tailnet-qa`** — `if-skip` is not a valid GitHub Actions keyword.
  Workflow parser rejects with `unexpected key "if-skip" for "job"
  section`. The step-level `if: matrix.lane.e2e` on line 164 already
  handles per-lane gating.

Both bugs surfaced during darkmap M3-completion PR #86 (TIN-1398).
Together they made v1.1.0 unusable for any spoke that calls
`spoke-ci.yml@v1.1.0` or `spoke-lane-env.yml@v1.1.0` directly. Ships
as v1.1.1.

### Changed

- **`spoke-lane-env.yml` — `BLAHAJ_DISPATCH_TOKEN: required: false`** —
  loosen the secret contract so spokes can keep the `pull_request:`
  trigger enabled before Blahaj is installed on the repo. New
  internal `check-blahaj-token` job runs first and gates every
  downstream job's `if:` on token presence — empty token = whole
  pipeline skips cleanly with a `::notice::`, NOT a workflow-file
  parse failure.

  Surfaced by darkmap M6 validation
  ([test PR #82](https://github.com/Jesssullivan/darkmap.tinyland.dev/pull/82)):
  GitHub resolves required secrets at workflow-call PARSE time,
  before the job-level `if:` evaluates. So `required: true` +
  empty caller secret = parse-time failure, and the gate never gets
  a chance to short-circuit. Reversing to `required: false` lets the
  job-level gate actually do its job. Backward-compatible: callers
  that DO have the secret continue to work identically.

### Added

- **`spoke-ci.yml` — new `runner_labels_json` optional input** —
  JSON-array expression evaluated via `fromJSON()` to set the
  per-lane matrix jobs' `runs-on`. When set (non-empty), takes
  precedence over `matrix.lane.runner_class` and
  `default_runner_class`.

  Enables spokes with dynamic runner-class fallback (e.g.
  `runs-on: ${{ fromJSON(vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '["ubuntu-latest"]') }}`)
  to adopt the `spoke-ci.yml` wrapper without losing graceful
  degradation when cluster labels aren't reachable.

  Surfaced by darkmap M3 partial (TIN-1384). Without this input,
  spokes with their own runner-routing logic (darkmap, MassageIthaca)
  couldn't replace their hand-rolled `ci.yml` with the wrapper.
  Now they can. Backward-compatible: existing callers that leave
  this unset see no behavior change.

## [1.0.1] — 2026-05-18

### Changed

- **`RELEASING.md` § Release flow** — documented the manual-tag
  fallback (step 3b) for environments where the workflow-driven
  release path (step 3a) doesn't hold. Specifically:
  - Local agent safety hooks blocking direct push to `main` and
    `release/*` branch patterns.
  - GitHub rebase-merge silently dropping empty commits — a
    `release: vX.Y.Z` empty commit landed via rebase-merge leaves
    `main` HEAD with a non-release subject, so `release.yml`'s
    `tag-on-release-commit` job never fires.
  Manual fallback cuts the immutable tag, moves the floating major
  tag, and creates the GH Release with the same CHANGELOG-extracted
  notes the automation would have produced. Surfaced during darkmap
  M1-M6 pilot (`Jesssullivan/darkmap.tinyland.dev` TIN-1381).

### Added

- **`docs/spec/dev-remote.md`** — full design spec for the v1.1+
  `lane-preview-tunnel` composite. Codifies the non-REAPI pathway
  (Blahaj K8s Deployment + tailscale-operator Service), the new
  `<spoke>-dev-env` event_type, the wire schema, lifecycle, auth
  model, and open questions to resolve before v1.1.0. Cross-linked
  from `docs/roadmap.md`. Doc-only — no behavior change.
- **`docs/release-checklist-v1.0.0.md`** — operator-facing
  step-by-step checklist for cutting the v1.0.0 release per
  `RELEASING.md`. Documents the merge → `release: v1.0.0` commit →
  `release.yml` auto-tag sequence, plus the companion-repo
  coordination (site.scaffold, GloriousFlywheel scoped tag,
  `.github` org ruleset application). Doc-only.

## [1.0.0] — 2026-05-17

First versioned release. All prior consumers were on `@main` and are
treated as v0.x retroactively (see `v0.4.0` below).

### Added

- **Workflow `release.yml`** — two-mode: on PR, assert `## [Unreleased]`
  is non-empty (forces CHANGELOG discipline); on push to `main`, if the
  head commit is `release: vX.Y.Z` then cut the immutable `vX.Y.Z` tag,
  move the floating `@vX` major tag, and create a GitHub Release with
  notes extracted from this CHANGELOG. Does NOT auto-tag arbitrary
  merges — matches the RELEASING.md flow.
- **Composite action `flywheel-bazel`** — wraps `bazelisk` with
  `--config=flywheel` (cache-only) or `--config=flywheel-executor`
  (cache + REAPI executor). Refuses executor mode on non-cluster runners.
  Ships embedded `bazelrc/flywheel.bazelrc`.
- **Composite action `lanes-load`** — reads + JSON-Schema-validates
  `.github/lanes.json`, outputs `lanes_json` (for matrix), `styles_json`,
  `lane_count`, `schema_version`, `spoke_name`, `spoke_domain`. Fixes the
  MassageIthaca lane-name duplication bug.
- **Composite action `lane-dispatch`** — constructs + emits the
  `<spoke>-lane-env` `repository_dispatch` to Blahaj (operation:
  `provision`). Validates payload against
  `schemas/blahaj-dispatch.schema.json`. Honors `lane-ttl/<N>d` PR labels.
  Supports `dry_run: true`.
- **Composite action `lane-reap`** — same shape with operation:
  `destroy`. Idempotent.
- **Composite action `lane-status-check`** — posts `ci/lane/<name>`
  GitHub commit status so branch protection can require per-lane checks.
- **Composite action `pulse-ingest-validate`** — wraps the
  `static-projection-snapshot.mts` script so spokes drop the local copy.
- **Reusable workflow `spoke-ci.yml`** — canonical spoke CI:
  secrets-scan → lanes-load → flywheel-bazel-build (per-lane matrix) →
  flywheel-bazel-test (per-lane matrix) → bazel-graph → optional
  playwright. Posts per-lane status checks.
- **Reusable workflow `spoke-lane-env.yml`** — canonical PR-env workflow:
  publish-image (per-lane matrix) → dispatch-apply (single
  `lane-dispatch` call carrying full lanes array) → optional tailnet-qa
  (per-lane matrix filtered to `e2e: true`) → destroy-lanes on PR close.
- **Reusable workflow `spoke-pulse-ingest.yml`** — generalized
  pulse-ingest workflow that opens snapshot-refresh PRs.
- **`schemas/lanes.schema.json`** + **`schemas/blahaj-dispatch.schema.json`** —
  vendored from `tinyland-inc/site.scaffold/docs/schemas/`. Composite
  actions validate inputs/outputs against these.
- **`bazelrc/flywheel.bazelrc`** — embedded Flywheel bazelrc fragment.
  `flywheel-bazel` action installs it to `.bazelrc.flywheel` at run time;
  spokes also vendor a copy and refresh via `just sync-flywheel-bazelrc`.
- **`docs/roadmap.md`** — v1.1+ items including `lane-preview-tunnel`
  (dev-server-on-cluster).
- **`RELEASING.md`** — release flow + SemVer policy.

### Changed

- **`nix-setup`** — added outputs `runner_class`, `attic_reachable`,
  `bazel_cache_reachable` consumed by `flywheel-bazel` for cluster
  detection. Bazel-cache DNS probe added (matching the existing Attic
  probe). Behavior-compatible with v0.x.
- **`secrets-scan`** — added input `extra_paths` (default `""`) for
  per-spoke `.gitleaks.toml` lookups outside the repo root; added
  output `findings_count` parsed from the gitleaks JSON report;
  added a `Secrets scan` block to `GITHUB_STEP_SUMMARY`. Behavior-
  compatible.
- **`nix-build`**, **`greedy-cache`** — internal `@main` self-references
  bumped to `@v1`.
- **`README.md`** — rewritten with v1.0.0 quick-start + pin banner.

### Migration from `@main`

See [`docs/migration-v0-to-v1.md`](docs/migration-v0-to-v1.md).
TL;DR: `grep -rn 'tinyland-inc/ci-templates.*@main' .github/` and
replace each `@main` with `@v1.0.0`. The four pre-existing composite
actions remain behavior-compatible; new spokes additionally consume
the reusable workflows.

## [0.4.0] — 2026-05-17 (retroactive baseline)

Snapshot of `@main` at the SHA preceding the v1.0.0 cut. Provided so
consumers on `@main` have a SemVer tag to pin against during migration.
No code changes from the pre-tag `@main` state.

### Pre-existing

- Composite actions `nix-setup`, `nix-build`, `greedy-cache`,
  `secrets-scan`.
- Reusable workflows `js-bazel-package.yml`, `npm-publish.yml`.
