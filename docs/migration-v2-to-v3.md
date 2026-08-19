# Migrating from `@v2.x` to `@v3.0.0` — no GitHub-hosted runners (TIN-3914)

`v3.0.0` removes every GitHub-hosted runner from this repository's reusable
workflows. Operator ruling, 2026-08-19, verbatim:

> we should NEVER have gh ubuntu runners in place ever, we ONLY use GF infra
> cache fronted runners

Every `runs-on` in `.github/workflows/*` now names a self-hosted org
capability-class label, and `scripts/lint-runs-on.rb` FAILs a GitHub-hosted
label wherever it can be read statically. There is no opt-out input: an
estate-wide prohibition with a "keep using hosted" knob would not be a
prohibition. That is why this is a MAJOR release rather than a default-off
addition (`AGENTS.md` rule 2) — see "Why MAJOR" below.

**Nothing changes until you bump your pin.** Immutable tags are immutable; a
spoke pinned to `@v2.13.0` keeps running exactly what it runs today.

## What actually changed

| Workflow | Job(s) | Before | After |
|---|---|---|---|
| `spoke-ci.yml` | `secrets-scan`, `lanes-load`, `repo-manifest` | `ubuntu-latest` | `inputs.default_runner_class` (default `tinyland-nix`), group-routed when `runner_group` is set |
| `spoke-lane-env.yml` *(deprecated)* | `check-blahaj-token`, `lanes-load`, `dispatch-apply`, `destroy-lanes` | `ubuntu-latest` | `tinyland-nix` |
| `js-bazel-package.yml` | `resolve-runner` | `ubuntu-latest` | `tinyland-nix` |
| `js-bazel-package.yml` | `validate`, `publish-npm`, `publish-github` | resolved from `runner_mode` / `publish_mode` | same resolution, minus the two retired hosted values |
| `npm-publish.yml` | `build-and-test`, `publish-gpr`, `publish-npm` | `ubuntu-latest` | `tinyland-nix` |
| `rust-bazel-application.yml` | `trust-gate` | `ubuntu-24.04` | `tinyland-nix` |
| `spoke-deploy-cloudflare-pages.yml` | `build` | `ubuntu-latest` | `tinyland-nix` |
| `spoke-public-preview.yml` | `dispatch` | `ubuntu-latest` | `tinyland-nix` |

`spoke-ci-restricted.yml`, `spoke-lane-env-restricted.yml` and
`spoke-pulse-ingest.yml` had no hosted path and are unchanged.

## Breaking: `js-bazel-package.yml` callers

Two previously-documented input values are **retired and rejected**, not
silently re-routed. A token-bearing publish job changing which machine it
executes on is a security-relevant change; it should be an edit you make, not
one that happens to you.

### `publish_mode: hosted_exception` → delete the line

```diff
     uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v3.0.0
     with:
       runner_mode: repo_owned
       runner_labels_json: ${{ vars.PRIMARY_LINUX_RUNNER_LABELS_JSON }}
-      publish_mode: hosted_exception
```

`same_runner` is now the only accepted value (it is also the default, so
deleting the line is the whole migration). Publish jobs run on the same
validated self-hosted capability class as `validate`.

**Consequence you must accept: npm provenance is no longer requested.** The
publish step only passes `npm publish --provenance` when
`runner.environment != 'self-hosted'`. That guard is unchanged, but publishes
are now always self-hosted, so `npm_publish_provenance: true` becomes inert and
the job emits a `::warning::` saying so. Packages published through this
template after the bump carry no npm provenance attestation. If a package's
policy requires provenance, do not bump its pin until a provenance-capable
self-hosted path exists — that is separate work, not part of TIN-3914.

### `runner_mode: hosted` → pick a capability class

```diff
-      runner_mode: hosted
+      runner_mode: repo_owned
+      runner_labels_json: '["tinyland-nix"]'
```

`compat`, `shared`, and `repo_owned` remain. All three now reject a
GitHub-hosted label in `runner_labels_json` / `shared_runner_labels_json`,
including in `compat` mode where labels were previously unvalidated.

### `runner_labels_json` default changed

The declared default was `'["ubuntu-latest"]'`; it is now `""`, which resolves
to `["tinyland-nix"]`. If you relied on the old default, name the class you
actually want. `runner_mode: repo_owned` still requires an explicit non-empty
value — the check now tests for emptiness rather than comparing against the old
hosted sentinel.

## Non-breaking-by-shape but behaviour-changing: `spoke-ci.yml` callers

No input changes. On the pin bump, three jobs that always ran on GitHub's fleet
start requesting your `default_runner_class`. Before bumping, confirm the class
you pass is actually served to the calling repository:

```bash
# the class every job now routes through
gh workflow view ci.yml --repo <owner>/<repo>   # confirm the inputs you pass
```

A tenant org whose pool is not `tinyland-nix` (e.g. Great-Falls-Tool-Bus, which
serves only `great-falls-tool-bus-nix`) must pass its own class:

```yaml
    with:
      default_runner_class: great-falls-tool-bus-nix
      heavy_runner_class: great-falls-tool-bus-nix
      kvm_runner_class: great-falls-tool-bus-nix
```

**Failure mode if you get this wrong: the job queues, it does not fall back.**
GitHub schedules a labelled job only onto a runner carrying that label; there is
no hosted degrade left to absorb the mistake. That is intentional — a missing
substrate is a deterministic failure, never a silent hosted build — but it means
"queued forever" replaces "ran somewhere unexpected" as the symptom of a bad
routing input.

`runner_group` now covers all seven jobs, not four. It remains default-off: with
`runner_group` unset, every job renders the plain label it renders today, proven
byte-for-byte by `just runner-group-contract-check`.

## `npm-publish.yml`, `spoke-deploy-cloudflare-pages.yml`, `spoke-public-preview.yml`

Literal `tinyland-nix`, with no new runner-class input. The 2026-08-19 fleet
sweep found zero callers of all three, so adding a caller-facing routing
contract would be inventing an interface for nobody. A tenant org that adopts
one of these and cannot reach `tinyland-nix` should file for the input rather
than reintroduce a hosted lane.

`npm-publish.yml`'s jobs use `actions/setup-node` and `pnpm/action-setup`, which
provision their own toolchains on a self-hosted runner; no Nix devshell wiring
was added.

## `rust-bazel-application.yml`

`trust-gate` moves to `tinyland-nix`. It deliberately stays a **bare label**
rather than `{group: inputs.runner_group, labels: …}`: its job is to validate
`runner_group` before any group-routed lane is scheduled, and routing the gate
through the value it validates would make an inadmissible group queue forever
instead of failing loudly.

## Capacity

Read `ARC pool facts` in the 2026-08-19 sweep before a broad pin bump. At the
time of writing, `tinyland-nix` is `min 0 / max 10` and
`great-falls-tool-bus-nix` is `min 0 / max 4`. This release adds these job
classes to those pools:

| New arrival on the pool | Per invocation | Live callers today |
|---|---|---|
| `spoke-ci` `secrets-scan` / `lanes-load` / `repo-manifest` | 3 short jobs (5–15 min timeouts) | 4 spokes |
| `spoke-lane-env` `check-blahaj-token` / `lanes-load` / `dispatch-apply` / `destroy-lanes` | 4 short jobs, per PR event | 2 spokes (deprecated lane) |
| `js-bazel-package` `resolve-runner` | 1 short job, on the critical path of **every** invocation | 68 call-sites (62 SHA-pinned to a 2026-05-27 commit; they arrive only as pins are bumped) |
| `npm-publish`, `spoke-deploy-cloudflare-pages`, `spoke-public-preview`, `rust-bazel` `trust-gate` | — | 0 |

`resolve-runner` is the one to watch: it is tiny but it gates every other job in
`js-bazel-package.yml`, so a burst of pin bumps across the ~68 call-sites can
saturate a max-10 pool and serialize package CI. Raise the `tinyland-nix`
`AutoScalingRunnerSet` max before doing a fleet-wide bump, and stage the bumps.

## Why MAJOR and not MINOR

`RELEASING.md` reserves MAJOR for "breaking changes to composite-action inputs,
reusable workflow inputs/secrets interface, schema major bumps", and MINOR for
"new actions / workflows, new optional inputs".

The MINOR case is real and worth stating: no input is removed, no input's type
changes, and every existing caller's YAML still parses and still passes schema.

It loses anyway:

1. **The accepted value domain of two declared inputs narrows.** `runner_mode`
   loses `hosted`; `publish_mode` loses `hosted_exception`. Both were
   documented, both are enforced in-workflow, and per the 2026-08-19 sweep all
   30 current publish call-sites pass `publish_mode: hosted_exception`. An enum
   is part of an input's interface; removing a value from it is a break.
2. **A declared default changes.** `runner_labels_json` goes from
   `'["ubuntu-latest"]'` to `""`/`["tinyland-nix"]`.
3. **Default execution behaviour changes with no opt-out, and fails hard.**
   Every consumer of six workflows gets jobs scheduled on runners that may not
   exist for them, and the failure mode is an indefinite queue, not a fallback.
   `AGENTS.md` rule 2 would normally require a default-off gate; this change
   deliberately has none, and an ungated behaviour change is exactly what a
   MAJOR is for.
4. **A supply-chain claim silently disappears** unless the release announces
   it: npm provenance stops being requested for `js-bazel-package.yml`
   publishes.
5. `RELEASING.md`'s migration discipline requires a `docs/migration-vN-to-vN+1.md`
   for a MAJOR. This document is that vehicle; a MINOR would not have one.

A MINOR is a promise that a pin bump is safe without reading the changelog.
That promise cannot be kept here. **`v3.0.0`.**

## Rollback

Pin back to the last v2 release and file the regression:

```yaml
uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v2.14.0
```

Do not point spokes at `@main` as a rollback path, and do not reintroduce a
hosted `runs-on` in a spoke as a workaround — `scripts/lint-runs-on.rb` FAILs it
and the ruling is estate-wide, not template-local.
