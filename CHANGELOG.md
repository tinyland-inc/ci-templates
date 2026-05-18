# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer 2.0](https://semver.org/).

## [Unreleased]

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
