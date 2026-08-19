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

## Breaking: `.github/lanes.json` may no longer name a hosted runner class

`schemas/lanes.schema.json`'s `runnerClass` carried an explicit
`{"const": "ubuntu-latest"}` arm, blessed in its own description "for jobs whose
entire purpose is a `gh api` call". That was the last sanctioned hosted path in
the estate, and it was invisible to every workflow-facing gate, because it is
**consumer data**: `lanes-load` validates your `lanes.json` against this schema
and emits `lanes_json`, which `spoke-ci.yml`'s `flywheel-build` / `flywheel-test`
resolve through `matrix.lane.runner_class` — straight into `runs-on`, on the
default path taken whenever `runner_labels_json` is unset.

The const arm is gone. A `gh api`-only lane runs on the base capability class
like everything else:

```diff
   "lanes": [
-    { "name": "api", "theme": "…", "snapshot_source": "…", "runner_class": "ubuntu-latest" }
+    { "name": "api", "theme": "…", "snapshot_source": "…", "runner_class": "tinyland-nix" }
   ]
```

Symptom if you miss it: `lanes-load` fails schema validation, so the whole
`spoke-ci` run stops at that job rather than silently scheduling a hosted build.
No consumer checkout surveyed used a hosted `runner_class`, so this closes a
hole rather than breaking live callers.

`schema_version` deliberately stays `1`. Bumping it would invalidate every
consumer's `lanes.json` over a *restriction* — a far larger break than the
restriction itself. The tightening rides this MAJOR instead; `just
lanes-schema-runner-class-check` proves no hosted label is representable, by
executing every accept-arm of the schema against hostile and legitimate label
sets rather than grepping the file.

## Non-breaking-by-shape but behaviour-changing: `spoke-ci.yml` callers

No input changes. On the pin bump, three jobs that always ran on GitHub's fleet
start requesting your `default_runner_class`. Before bumping, confirm the class
you pass is actually served to the calling repository:

```bash
# Which classes are actually SERVED to this repository? This is the check that
# matters — reading your own caller file only tells you what you asked for.
gh api /repos/<owner>/<repo>/actions/runners --jq '[.runners[].labels[].name] | unique'
# org-level pools (a repo-level query does not see them):
gh api /orgs/<org>/actions/runners --jq '[.runners[].labels[].name] | unique'
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
was added. Its `publish-npm` job requested `npm publish --provenance`
unconditionally; see the provenance note above — it is now gated the same way
`js-bazel-package.yml`'s is, because on a self-hosted runner npm *rejects* the
publish rather than merely dropping the attestation.

## `js-bazel-package.yml`'s `resolve-runner` label is hard-coded — read this if you are out-of-org

`resolve-runner` is a literal `tinyland-nix` with no input, and it gates every
other job in the workflow (`validate`, `publish-npm`, `publish-github` all read
their `runs-on` from its outputs). `tinyland-nix` is a `tinyland-inc` org pool:
a caller in another org cannot schedule it at all, and per the failure-mode note
below the symptom is an **indefinite queue**, which means the carefully-worded
`hosted_exception` migration error never gets a chance to print.

The zero-callers argument used for `npm-publish.yml` and friends does not extend
to a workflow with 68 call-sites, so it was checked rather than assumed: **all
36 distinct caller repositories in the 2026-08-19 sweep are in `tinyland-inc`**,
and `tinyland-nix` is shared across that whole org. There is therefore no
out-of-org caller to break today.

**If you are adopting `js-bazel-package.yml` from another org, do not bump to
`v3.0.0` yet** — file for a `resolve_runner_class` input first. Deliberately not
added in this release: a new caller-controlled input that selects the runner for
the job that validates runner selection is a bootstrap the prohibition cannot
gate (a hosted value would schedule a hosted runner and only then fail), and
inventing that in the release that forbids hosted runners is the wrong order.

## `rust-bazel-application.yml`

`trust-gate` moves to `tinyland-nix`. It deliberately stays a **bare label**
rather than `{group: inputs.runner_group, labels: …}`: its job is to validate
`runner_group` before any group-routed lane is scheduled, and routing the gate
through the value it validates would make an inadmissible group queue forever
instead of failing loudly.

## Capacity

Before a broad pin bump, re-read the live pool state — the numbers below are a
2026-08-19 snapshot from the fleet sweep's `ARC pool facts` section, taken with
`kubectl --context honey get autoscalingrunnersets -A`, and capacity is the one
input to this decision that changes without a PR. At that snapshot
`tinyland-nix` was `min 0 / max 10` and **already at 9 current / 5 running**,
and `great-falls-tool-bus-nix` was `min 0 / max 4` at 0. Roughly one spare slot
is the headroom this release is landing into. This release adds these job
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

## What will fail after you bump

Two different things break at two different times. Keep them apart or you will
either panic or under-prepare.

### Immediately, on the pin bump

| Symptom | Cause | Fix |
|---|---|---|
| `Unsupported publish_mode` / `runner_mode` error in `resolve-runner` | you pass `publish_mode: hosted_exception` or `runner_mode: hosted` | delete the line / pick a capability class (above) |
| `lanes-load` fails schema validation | `.github/lanes.json` names a hosted `runner_class` | use a capability class (above) |
| a job sits in **Queued** forever | the capability class you pass is not served to this repo | check the runners API (above), pass your org's class |
| published package silently loses its npm provenance attestation | publishes are now self-hosted | accept it, or hold the pin (above) |

### Later, the first time you wire the `runs-on` gate

`lint-runs-on` is a composite action; **no reusable workflow in this repo
invokes it**, and no consumer invoked it as of the 2026-08-19 sweep. So the
tightened linter does not retroactively fail your existing jobs on a pin bump —
it fails them the day you adopt the gate. That makes the following numbers
latent rather than urgent, and it is exactly why they are published here instead
of being discovered one repo at a time.

Running the `v3.0.0` linter over every local checkout that references
`tinyland-inc/ci-templates` (**50 consumer repos**, self-checkouts excluded):

```
base (v2.14.0 linter)   4 FAIL across  2 repos
head (v3.0.0 linter)   99 FAIL across 21 repos
                    -> 95 NEW FAILs across 20 repos (40% of consumers)
```

Reproduce for one repo: `ruby scripts/lint-runs-on.rb --root <repo>`.
Extrapolated to the ~190-repo fleet, expect roughly **75 repos** to need edits.

| Repo | base | head | new |
|---|---|---|---|
| `tinyland.dev` | 0 | 17 | 17 |
| `darkmap.tinyland.dev` | 0 | 14 | 14 |
| `site.scaffold` | 0 | 8 | 8 |
| `fuzzy-crush` | 1 | 8 | 7 |
| `canon-megatank-reset` | 0 | 6 | 6 |
| `transfemme-tailoring` | 0 | 5 | 5 |
| `software.tinyland.dev` | 0 | 5 | 5 |
| `formal_transfemme_sewing` | 0 | 5 | 5 |
| `greatfallstoolbus.org` | 0 | 4 | 4 |
| `gdrive-mounts` | 0 | 4 | 4 |
| `acuity-middleware` | 0 | 3 | 3 |
| `tinyland-a11y-engine` | 0 | 3 | 3 |
| `massage-ithaca-portal` | 0 | 2 | 2 |
| `lab` | 2 | 4 | 2 |
| `MassageIthaca`, `gftb-site`, `great-falls-tool-bus-infra`, `printstack`, `software.tinyland.dev-booking`, `tinyland-schemas` | 0–1 | 1 | 0–1 |

Every one of the 99 falls into three classes. There is no long tail:

**Class 1 — bare hosted literal (75 of 99, all new).**
`runs-on: ubuntu-latest` (71), `macos-15` (2), `ubuntu-24.04` (1),
`macos-latest` (1). Fix: name a capability class.

```diff
-    runs-on: ubuntu-latest
+    runs-on: tinyland-nix
```

**Class 2 — hosted label baked into a `fromJSON` fallback (20 of 99, all new).**
The "graceful degradation when cluster labels are not reachable" pattern:
`${{ fromJSON(vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '["ubuntu-latest"]') }}`
(16), plus `CONTAINER_` (2) and `BAZEL_LINUX_` (2) variants. The linter blessed
this shape before `v3.0.0`; it is a FAIL now, because there is nothing left to
degrade *to*. Keep the variable, fix the fallback:

```diff
-    runs-on: ${{ fromJSON(vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '["ubuntu-latest"]') }}
+    runs-on: ${{ fromJSON(vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '["tinyland-nix"]') }}
```

Expect a WARN to remain: the variable itself is still opaque at author time, and
`v3.0.0` floors a partly-resolvable expression at WARN rather than passing it.
WARN is not a failure — `--strict` is opt-in.

**Class 3 — non-canonical self-hosted array (4 of 99, none new).**
`["self-hosted","Linux","X64","honey","nix"]`, `["self-hosted","printbox"]`,
`["self-hosted","macOS","ARM64","darwin"]`. These already failed under
`v2.14.0`; they are host pins and bespoke labels, not capability classes. Fix:
reduce to the capability class the pool actually serves.

```diff
-    runs-on: ${{ fromJSON(vars.LAB_FLEET_DEPLOY_RUNNER_LABELS_JSON || '["self-hosted","Linux","X64","honey","nix"]') }}
+    runs-on: ${{ fromJSON(vars.LAB_FLEET_DEPLOY_RUNNER_LABELS_JSON || '["tinyland-nix"]') }}
```

## Rollback

Pin back to the last v2 release and file the regression:

```yaml
uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@v2.14.0
```

A spoke pinned to `@v2.x` or to a commit SHA is not affected by any of this and
needs no action — immutable tags are immutable, and nothing here reaches back
into a release you already pinned. The only event that opts you in is bumping
the pin.

Do not point spokes at `@main` as a rollback path, and do not reintroduce a
hosted `runs-on` in a spoke as a workaround — `scripts/lint-runs-on.rb` FAILs it
and the ruling is estate-wide, not template-local.
