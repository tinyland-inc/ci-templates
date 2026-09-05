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

1. **Pin, don't float.** Production consumers pin an exact immutable release
   such as `@v2.12.1`; floating `@v2` is a quick-start convenience, not an
   acceptance receipt. The restricted private-runner workflows and their full
   transitive composite closure must use an exact immutable self-release, while
   third-party Actions use full 40-character commit SHAs. The restricted
   closure check rejects `@v2`, `@main`, local consumer-relative actions,
   unpinned third-party Actions, mutable installer scripts, and unverified
   scanner archives.
2. **Default-off, opt-in changes only.** A new behavior added to a shared
   workflow MUST be gated behind a new input that defaults to the pre-existing
   behavior. Non-opted consumers must be byte-identical. Prove it by diffing the
   default execution path. There are three standing exceptions. Rule 3 is a
   prohibition and cannot ship with an opt-out, so TIN-3914 changed default
   routing for every consumer and took a MAJOR bump instead of a gate. TIN-4257
   repairs the already-declared schema-3 export contract by always passing the
   image-custodied client a fresh result directory: a workflow input would
   become a second result-disposition authority beside the ActionPlan. That
   caller repair ships only in a new immutable patch after the provider image
   accepts the flag; it never moves an existing exact tag. TIN-4299 ruling 4
   makes the pooled Nix cache read edge (`nix-setup`, `nix-build`,
   `greedy-cache` `attic-public-read`) default-on and fail-closed: a
   consumer that never declared trust must not silently build cache-less or
   substitute from an unverified cache, so the default flipped and the edge
   hard-fails on an absent key or unreachable substituter; it takes a MAJOR
   bump, and `attic-public-read: "false"` remains the explicit, byte-identical
   opt-out for lanes that never touch Nix.
3. **No GitHub-hosted runners, ever.** Operator ruling, 2026-08-19: the estate
   runs ONLY on GF cache-fronted self-hosted runners. Every `runs-on` names an
   org capability class. Three gates, deliberately reading different things:
   `just lint-runs-on-check` verdicts `runs-on` values structurally,
   `just no-hosted-runners-check` scans every schedulable surface textually
   (label-aware and case-insensitive). The v4 action-plan schema cannot express
   a runner at all. There is no opt-out input, and reintroducing one is not a
   local decision. See
   `docs/migration-v2-to-v3.md`.
4. **No baked endpoints, credentials, or upload authority** in `bazelrc/*.bazelrc`
   (enforced by `just endpoint-free-check` + `just ci-cached-endpoint-free-check`).
   Cache/executor endpoints are runtime authority, supplied as flags by the
   composite/workflow from validated env.
5. **Amend `CHANGELOG.md` `## [Unreleased]`** in every feature/fix PR. Release
   PRs move that content into the dated version section.
6. **Run `just check` before pushing** (or `nix develop --command just check`).

## Local validation

```bash
just check                       # full suite
nix develop --command just check # if tools are not on PATH
```

`just check` parses all workflow/action YAML + JSON schemas, validates
`tinyland.repo.json`, asserts internal action refs resolve, traverses the
restricted workflows' exact dependency closure, guards the js-bazel-package
runner + cache-backed contracts, asserts the bazelrc fragments stay
endpoint-free, dogfoods the `runs-on` linter at 0 FAIL, proves no GitHub-hosted
runner label survives on a schedulable surface, including canonical consumer
lanes data (`no-hosted-runners-check`, TIN-3914), and runs the gitleaks
working-tree scan.

## V4 action-fabric release (TIN-2130, TIN-4246, TIN-4249)

The only adoption target is ActionPlan/v4 schema 3 through
`spoke-ci-v4.yml@v5.1.0` or newer. An organization installs its own all-repos GF
GitHub App and operates its own owner controller, resolver, and thin
`gf-v4-dispatch` edge. Each application repository contributes only a finite
`.github/lanes.json` and an immutable workflow call. GF and ci-templates never
hold consumer rows, repository enrollment, provider endpoints, or overlay
instances.

The workflow checks out the exact admitted source SHA and invokes one compiled
client command:

```text
/usr/local/bin/gf-action-client run \
  --plan .github/lanes.json \
  --action "$ACTION_NAME" \
  --source-sha "$SOURCE_SHA" \
  --result-dir "$RUNNER_TEMP/gf-action-result-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${ACTION_NAME}"
```

The Go client owns OIDC, invocation-time binding, REAPI dispatch, cache reuse,
and `ActionOutputSet/v1` carriage. Bazel actions—not GitHub jobs or ARC pods—are
the compute and scheduling unit. The `gf-v4-dispatch` runner is an org-local
teletype into that fabric, not provider supply.

Missing App, overlay revision, owner-supply catalog, dynamic binding, OIDC,
client, REAPI authority, or result is a hard product failure. There is no v4
fallback to a v3 profile or registry, cache-only attachment, local build,
hosted runner, direct endpoint, environment profile, or warning-success path.
Historical cache/profile workflows remain retirement inventory; they are not
an adoption guide and must disappear from a consumer's v4 cutover.

## Releasing

See `RELEASING.md`. Releases are attended operator transactions: enable native
immutable releases, land the dated changelog section, create signed annotated
exact and floating-major tags with an exact lease, then publish and verify the
GitHub release attestation. Never reuse an exact tag.
