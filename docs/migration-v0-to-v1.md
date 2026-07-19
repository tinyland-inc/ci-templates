# Migrating from `@main` to `@v1.0.0`

> Historical v1 record: v1/v2 named build-only statuses
> `ci/lane/<name>`. That legacy name never proved a deployed runtime. Current
> main preserves it byte-for-byte by default and offers a coordinated opt-in to
> `ci/build/<name>`; see the README.

`@main` is the develop branch from v1.0.0 onward and **breaks without
notice**. All consumers should pin to `@v1.0.0` (or the latest
`v1.x.y`).

## Mechanical migration

```bash
# Find existing @main references
grep -rn 'tinyland-inc/ci-templates.*@main' .github/

# Replace them
find .github -name '*.yml' -print0 \
  | xargs -0 sed -i.bak 's|tinyland-inc/ci-templates/\([^@]*\)@main|tinyland-inc/ci-templates/\1@v1.0.0|g'
find .github -name '*.bak' -delete
```

Existing actions are behavior-compatible (see CHANGELOG `### Changed`),
so the mechanical swap is all most consumers need.

## What's new in v1.0.0 that you may want to adopt

If you currently hand-roll a `pr-env-lanes.yml` (e.g. MassageIthaca-style),
replace it with the `spoke-lane-env.yml` reusable workflow:

```yaml
# .github/workflows/lane-env.yml
name: Lane env
on:
  pull_request:
    types: [opened, synchronize, reopened, closed]

jobs:
  lane-env:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-lane-env.yml@v1.0.0
    with:
      spoke: massageithaca
      enable_tailnet_qa: true
    secrets: inherit
```

You also need `.github/lanes.json` matching
`schemas/lanes.schema.json`. See
`tinyland-inc/site.scaffold/docs/CI-SCHEMA.md` for the contract and
`tinyland-inc/site.scaffold/.github/lanes.example.json` for a
three-lane reference.

## Behavior changes you should know about

- **Lane names are derived from `lanes.json`, not duplicated in workflow
  YAML.** If you removed `PR_ENV_TARGETS_JSON` and the bespoke `styles`
  array, the new workflow handles both via `lanes-load`.
- **Per-PR TTL override via PR labels**: apply `lane-ttl/24h` or
  `lane-ttl/keep` to a PR to raise the TTL. Hardcoded 72h is gone.
- **Per-lane GitHub commit status checks** named `ci/lane/<name>` are
  posted by the flywheel-build job. They do not prove tests, a route, or runtime
  environment. Only require them according to that historical meaning; migrate
  names and branch rules together when adopting `ci/build/<name>`.
- **E2E inclusion is per-lane data**, not workflow-hardcoded. Set
  `e2e: true` on each lane that should run tailnet-qa.
- **Dry-run testability**: `lane-dispatch` accepts `dry_run: true` so
  Blahaj isn't a hard dependency for CI rehearsal.

## Rollback

If v1.0.0 introduces an unexpected regression, pin to v0.4.0 (the
retroactive baseline tag of `@main`):

```yaml
uses: tinyland-inc/ci-templates/.github/actions/...@v0.4.0
```

Open an issue describing the regression so it can be fixed in v1.0.1.
