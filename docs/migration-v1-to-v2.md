# Migrating from `@v1.x` to `@v2.0.0`

`v2.0.0` is the Tinyland spoke-conformance release. It removes endpointful
Flywheel defaults from the reusable Bazel surface and adds scaffold skills
inheritance for agent-facing repo setup.

## Mechanical migration

Replace ci-templates workflow and action pins in spoke workflows:

```bash
find .github -name '*.yml' -print0 \
  | xargs -0 sed -i.bak 's|tinyland-inc/ci-templates/\([^@]*\)@v1\([.0-9]*\)|tinyland-inc/ci-templates/\1@v2.0.0|g'
find .github -name '*.bak' -delete
```

Then run the repo's normal gate:

```bash
nix develop --command just check
nix develop --command just conformance
```

## Flywheel endpoint change

`bazelrc/flywheel.bazelrc` is now endpoint-free. It no longer embeds an
in-cluster remote cache or remote executor URL.

Runtime authority comes from environment supplied by the spoke wrapper, runner,
or operator job:

- `BAZEL_REMOTE_CACHE` is required for Flywheel-backed Bazel work.
- `GF_BAZEL_SUBSTRATE_MODE=shared-cache-backed` uses cache only.
- `GF_BAZEL_SUBSTRATE_MODE=executor-backed` also requires
  `BAZEL_REMOTE_EXECUTOR`.
- `GF_BAZEL_REMOTE_UPLOAD=true` is only for trusted default-branch or operator
  cache-writing jobs.

Pull-request jobs should keep upload false or unset.

## Scaffold skills inheritance

Static spokes can inherit the scaffold agent/AX package from a pinned
`site.scaffold` tag:

```yaml
steps:
  - uses: actions/checkout@v6
  - uses: tinyland-inc/ci-templates/.github/actions/inherit-scaffold-skills@v2.0.0
    with:
      scaffold_ref: v2026.05.19
```

The action copies `plugins/scaffold-core`, dereferences skill symlinks so the
consumer checkout is self-contained, copies skill bodies into `.agents/skills`,
and creates `.claude/skills` symlinks for Claude Code discovery.

Use `mode: check` when you want CI to fail on stale checked-in inherited skills
instead of rewriting the workspace.

## Internal action refs

Reusable v2 workflows call sibling ci-templates actions through the floating
`@v2` major tag. This keeps `spoke-ci.yml@v2.0.0` from accidentally invoking
older v1 composites.

## Rollback

If v2 introduces an unexpected regression, pin the affected workflow back to
the latest v1 release while filing the regression against Tinyland:

```yaml
uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v1.1.5
```

Do not point spokes at `@main` as a rollback path.
