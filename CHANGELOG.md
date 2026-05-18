# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer 2.0](https://semver.org/).

## [Unreleased]

## [1.0.0] — 2026-05-17

First versioned release. All prior consumers were on `@main` and are
treated as v0.x retroactively (see `v0.4.0` below).

### Added

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
  detection. Behavior-compatible with v0.x.
- **`nix-build`**, **`greedy-cache`** — internal `@main` self-references
  bumped to `@v1`.
- **`secrets-scan`** — added inputs `extra_paths` (default `""`) and
  output `findings_count`. Behavior-compatible.
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
