# AGENTS.md — tinyland-inc/ci-templates

Operator/agent guide for the shared Tinyland CI surface. This repo is a
**reusable** GitHub Actions library consumed by ~190 repos. Treat every change as
a fleet-wide change.

## What this repo is

- Reusable **workflows** (`.github/workflows/*.yml` with `workflow_call`) and
  composite **actions** (`.github/actions/*/action.yml`) that spokes pin and
  consume. It is not an application; nothing here deploys.
- The contract spokes conform to lives in
  `tinyland-inc/site.scaffold/docs/CI-SCHEMA.md`. This repo vendors schemas at
  stable paths under `schemas/`.

## Golden rules

1. **Pin, don't float.** Consumers pin `@v2.x` (immutable) or the floating major
   `@v2`. Internal composite-to-composite refs use the floating major (`@v2`),
   never `@main` (enforced by `scripts/validate-ci-templates.py internal-refs`).
2. **Default-off, opt-in changes only.** A new behavior added to a shared
   workflow MUST be gated behind a new input that defaults to the pre-existing
   behavior. Non-opted consumers must be byte-identical. Prove it by diffing the
   default execution path.
3. **No baked endpoints, credentials, or upload authority** in `bazelrc/*.bazelrc`
   (enforced by `just endpoint-free-check` + `just ci-cached-endpoint-free-check`).
   Cache/executor endpoints are runtime authority, supplied as flags by the
   composite/workflow from validated env.
4. **Amend `CHANGELOG.md` `## [Unreleased]`** in every PR (gated by `release.yml`).
5. **Run `just check` before pushing** (or `nix develop --command just check`).

## Local validation

```bash
just check                       # full suite
nix develop --command just check # if tools are not on PATH
```

`just check` parses all workflow/action YAML + JSON schemas, validates
`tinyland.repo.json`, asserts internal action refs resolve, guards the
js-bazel-package runner + cache-backed contracts, asserts the bazelrc fragments
stay endpoint-free, and runs the gitleaks working-tree scan.

## Bazel cache enrollment (cache-first, TIN-1997 Option D / TIN-2110)

The `js-bazel-package.yml` workflow has an **opt-in, default-off** cache-backed
Bazel validation lane. It is the canonical template for fanning shared-cache
enrollment out to spokes.

- **Doctrine: cache-first only.** This lane reads/writes the shared Bazel cache.
  It does NOT wire a remote executor / REAPI. Remote execution is out of scope;
  the `flywheel-bazel` composite + `flywheel-reapi-proof` cover executor lanes
  separately.
- **Enroll** by setting `cache_backed: true` on the `js-bazel-package.yml`
  consumer call. When unset, the existing plain
  `bazelisk build … --verbose_failures` path runs byte-identically.
- **Endpoints are never baked.** `bazelrc/ci-cached.bazelrc` defines endpoint-free
  `:ci-cached` behavior; the workflow injects `--remote_cache=$BAZEL_REMOTE_CACHE`
  after the fail-closed `scripts/cache-attachment-contract.sh --strict` gate.
  On self-hosted Tinyland cluster runners, `nix-setup` exports
  `BAZEL_REMOTE_CACHE` from cluster DNS — no new secret or infra required.
- **Do NOT** create per-repo runners, bespoke cache instances, localhost/
  port-forward endpoints baked into config, or static long-lived cache secrets.
  Route everything through this shared surface + the GloriousFlywheel substrate.
- **Real attach, not nominal.** Enrollment counts only when the build log shows
  remote cache hit/transfer lines. A green build on a `tinyland-nix` runner with
  only `--disk_cache` is NOT enrollment and must be reported as such.
- **Self-verify** locally with `scripts/cache-attachment-contract.sh --strict`
  (classifies `compatibility-local-only` / `shared-cache-backed` /
  `executor-backed`; rejects unexpanded `${…}` placeholders, non-`grpc`/`http`
  endpoints, and localhost without `GF_BAZEL_ALLOW_LOCALHOST_PROOF=true`).

See `docs/js-bazel-package.md` (`cache_backed`) for the consumer-facing details.

## Releasing

See `RELEASING.md`. On a `release: vX.Y.Z` commit to `main`, `release.yml` cuts
the immutable tag and moves the floating major. Never reuse or force a tag
out-of-band.
