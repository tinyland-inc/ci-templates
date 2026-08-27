# JS Bazel Package Workflow

`js-bazel-package.yml` is the reusable workflow for JavaScript and TypeScript
packages whose authoritative publish artifact is built by Bazel rather than
published directly from the workspace tree.

It is meant for packages like:

- `@tummycrypt/scheduling-kit`
- `@tummycrypt/tinyvectors`
- `@tummycrypt/scheduling-bridge`

## What it does

- makes runner intent explicit with `runner_mode`
- makes workspace hygiene explicit with `workspace_mode`
- makes publish authority explicit with `publish_mode`
- makes npmjs authority explicit with `npm_publish_mode`
- installs the workspace with pnpm
- configures Attic and Bazel cache hints on self-hosted runners
- optionally keeps legacy cleanup-based workspace behavior for migration
- optionally stages validation work in an isolated scratch workspace
- runs optional metadata, lint, typecheck, unit, and integration commands
- optionally verifies a committed Bzlmod lock or emits a remotely refreshed
  `MODULE.bazel.lock` artifact
- builds the workspace artifact
- validates the Bazel-built package via `npm pack --dry-run`
- validates npm publish dry-runs against the Bazel artifact unless npmjs is
  disabled
- optionally validates GitHub Packages dry-runs after rewriting package metadata
- uploads the Bazel-built package artifact for publish jobs
- publishes from the same self-hosted runner class that validated the artifact

## Contract inputs

### `runner_mode`

Allowed values:

- `compat`
- `shared`
- `repo_owned`

`hosted` was **retired by TIN-3914** (`v3.0.0`) and is now rejected with a
migration error. The estate has no GitHub-hosted runners; see
[`migration-v2-to-v3.md`](migration-v2-to-v3.md).

Meaning:

- `compat`
  - preserve the legacy `runner_labels_json` behavior
  - use this only as a migration bridge
  - since `v3.0.0` the unset default resolves to `["tinyland-nix"]` (it was
    `["ubuntu-latest"]`), and a GitHub-hosted label passed here is rejected
- `shared`
  - validate and publish on a documented shared GloriousFlywheel lane
  - pass a non-empty `shared_runner_labels_json`; an empty value is rejected
    because it usually means the caller repo variable is missing
  - labels must include an org capability-class label
- `repo_owned`
  - validate and publish on a repo/owner-scoped runner registration path
  - workflow-facing labels still stay org capability classes
  - labels must include an org capability-class label

`repo_owned` is a trust and registration boundary, not permission to mint
known repo-label fossils. GloriousFlywheel keeps runner labels capability-based
(`tinyland-nix`, `great-falls-tool-bus-nix`, and related classes); owner/repo
separation belongs in ARC registration identity, runner groups, GitHub App
installation, and implementation-overlay policy.

### `workspace_mode`

Allowed values:

- `isolated`
- `persistent_compat`

Meaning:

- `isolated`
  - checkout normally
  - copy the repo into a per-job scratch directory under `$RUNNER_TEMP`
  - run validation there
- `persistent_compat`
  - keep the old cleanup-based model for long-lived self-hosted workspaces

### `publish_mode`

Allowed values:

- `same_runner`

`hosted_exception` was **retired by TIN-3914** (`v3.0.0`). It is rejected with a
migration error rather than silently re-routed: a token-bearing publish job
changing which machine it executes on should be an edit the caller makes, not
one that happens to them. Delete the line — `same_runner` is the default.

Meaning:

- `same_runner`
  - publish from the same runner class that validated the Bazel artifact

**Consequence of the retirement:** publishes are now always self-hosted, and the
publish step only passes `npm publish --provenance` when
`runner.environment != 'self-hosted'`. That guard is unchanged, so
`npm_publish_provenance` is now inert and **npm provenance is no longer
requested**. The job emits a `::warning::` saying so rather than dropping the
supply-chain claim silently. A package whose policy requires provenance should
not bump its pin until a provenance-capable self-hosted path exists.

### `npm_publish_mode`

Allowed values:

- `required`
- `optional`
- `disabled`

Meaning:

- `required`
  - preserve the legacy npmjs contract
  - validate npmjs dry-runs
  - require `secrets.NPM_TOKEN` before real npmjs publication
  - fail the workflow when npmjs publish fails
- `optional`
  - keep npmjs validation and publication as best-effort compatibility
  - skip real npmjs publication when `secrets.NPM_TOKEN` is absent
  - warn, but do not fail, when npmjs dry-run or publish fails
- `disabled`
  - skip npmjs dry-run validation and npmjs publication
  - use this for Bazel-first packages whose release authority is GitHub
    tag/release, GitHub Packages, and the Tinyland Bazel registry

### Bzlmod lock controls

`verify_bzlmod_lock` and `emit_bzlmod_lock_artifact` are independent, opt-in
boolean inputs. Both default to `false`; with both unset, the legacy cleanup
and Bazel target command run unchanged.

- `verify_bzlmod_lock: true`
  - requires a clean, tracked root `MODULE.bazel.lock`
  - preserves that file even when the legacy `cleanup_paths` default includes it
  - runs `bazelisk mod deps --lockfile_mode=update` and fails if the committed
    lock changes
  - runs the subsequent Bazel target validation with
    `--lockfile_mode=error`, then checks the lock again
- `emit_bzlmod_lock_artifact: true`
  - preserves an existing root lock, but may also generate the first lock for a
    new package
  - refreshes the lock with `--lockfile_mode=update`, then validates targets
    with `--lockfile_mode=error`
  - uploads the result as the `bzlmod-lock` Actions artifact from the matrix lane
    matching `publish_node_version`

When both inputs are true, committed-lock verification remains fail-closed and
the unchanged lock is also uploaded. The refresh/verification step checks that
it is actually running on a GF self-hosted capability runner; there is no local
or GitHub-hosted fallback. The artifact is evidence for a reviewed follow-up
commit—the workflow never commits or pushes a consumer lock itself. Ensure
`publish_node_version` is present in `node_versions` when requesting the
artifact.

### `cache_backed`

Opt-in (default `false`) shared-cache-backed Bazel validation. This is the
TIN-2110 cache-first enrollment surface (TIN-1997 Option D, proven by GF#889).

- `false` / unset (default)
  - the Bazel target validation runs the existing plain
    `npx --yes @bazel/bazelisk build <targets> --verbose_failures` path,
    byte-identically. Non-opted consumers see zero behavior change.
- `true`
  - the consumer's `tinyland.repo.json` is validated against the vendored
    ci-templates schema (network-free); an invalid manifest **fails closed**
    (TIN-2109)
  - a fail-closed cache-attachment contract step runs next
    (`scripts/cache-attachment-contract.sh --strict`), rejecting unexpanded
    `${...}` placeholders, non-`grpc`/`http` endpoints, and localhost endpoints
    (unless `GF_BAZEL_ALLOW_LOCALHOST_PROOF=true`)
  - the contract's **expected mode is manifest-driven** (TIN-2109): it is read
    from `enrollment.substrateMode` in `tinyland.repo.json`. If the manifest
    declares `shared-cache-backed` but no cache actually attaches, the lane
    **fails closed** (declared-vs-actual mismatch) instead of silently degrading
  - the workflow exports `GF_FLYWHEEL_PROFILE_STATE` from the resolved substrate
    mode so consumer `flywheel-doctor` / `flywheel-verify` commands see the
    same machine-readable attachment state as CI
  - the contract **rejects hosted / non-cluster runner fallback**: the runner
    labels are inspected and a GitHub-hosted (`ubuntu-*`), bare `self-hosted`, or
    known repo-label fossil is a deterministic failure, never a silent degrade
    to a hosted build (override only with
    `GF_BAZEL_ALLOW_HOSTED_RUNNER=true`)
  - the Bazel validation then runs
    `--config=ci-cached --remote_cache=$BAZEL_REMOTE_CACHE
    --remote_upload_local_results=false`, reading the shared Bazel cache
  - the lane fails closed when `BAZEL_REMOTE_CACHE` is unset rather than
    silently building local-only

`cache_backed` is **cache-first only**. It never wires a remote executor; REAPI /
remote execution is out of scope for this lane (the workflow contains no
executor flag or endpoint). On self-hosted Tinyland cluster runners, `nix-setup`
exports `BAZEL_REMOTE_CACHE` from cluster DNS, so attach needs no new secret or
infrastructure; off-cluster, supply the endpoint via a repo/org secret or a
wrapping step before validation.

The contract script also **defines and enforces** the `executor-backed` contract
for any repo that declares `enrollment.substrateMode: executor-backed`: it then
requires the full set (remote executor endpoint + `BAZEL_REMOTE_CACHE` + a
cluster runner class for platform identity + a digest-pinned REAPI proof image,
`GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST`) and fails closed if any piece is missing.
**No current repo selects executor-backed** (cache-first / Option D); the contract
is defined so the gate is enforceable the moment a repo declares it.

Consumers opting in must:

1. set `cache_backed: true` in the `with:` block
2. vendor `bazelrc/ci-cached.bazelrc` behavior in their `.bazelrc` (a base `:ci`
   config that empties `--disk_cache=` in CI plus the `:ci-cached` block) so a
   green build proves the **remote** cache, not an incidental disk hit
3. optionally vendor `scripts/cache-attachment-contract.sh` for the same
   fail-closed self-check locally (`scripts/cache-attachment-contract.sh
   --strict`); the workflow falls back to fetching the pinned ci-templates copy
   when the consumer has not vendored it

Real enrollment is proven by remote cache hit/transfer lines in the cache-backed
validation step log. A green build that shows only `--disk_cache` and no remote
transfer is **not** enrollment.

When the consumer has not vendored `scripts/cache-attachment-contract.sh`, the
workflow fetches it from an **immutable releasing tag** (the fallback ref is
pinned to `v2.5.1`, not the floating `v2` major), so pure-consumer spokes get a
reproducible fetch.

### `substrate_mode`

Optional operator override for the cache-backed lane's expected substrate mode
(`compatibility-local-only` | `shared-cache-backed` | `executor-backed`). It is
used **only** when `cache_backed: true` and the consumer's `tinyland.repo.json`
does not declare `enrollment.substrateMode` — the manifest is the authoritative
source (TIN-2109). When both are empty the lane defaults to
`shared-cache-backed`. This input has no effect on the default
(non-cache-backed) path.

### `github_package_name`

`github_package_name` is the package coordinate used only for the GitHub
Packages artifact. It may intentionally differ from the npmjs package name.

GitHub Packages npm scopes are owner-bound, so the scope must match the GitHub
account or organization that owns the package. For a `tinyland-inc/*` repository
whose public npm package is `@tummycrypt/tinyland-auth`, use a GitHub Packages
mirror name such as `@tinyland-inc/tinyland-auth`.

## Example: repo-owned capability-class package path

```yaml
name: CI

on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v2.0.0
    with:
      runner_mode: repo_owned
      runner_labels_json: ${{ vars.PRIMARY_LINUX_RUNNER_LABELS_JSON }}
      workspace_mode: isolated
      publish_mode: same_runner
      prepare_command: pnpm exec svelte-kit sync
      metadata_check_command: pnpm check:release-metadata
      lint_command: pnpm lint
      typecheck_command: pnpm check
      unit_test_command: pnpm test:unit
      integration_test_command: pnpm test:integration
      build_command: pnpm build
      package_check_command: pnpm check:package
      bazel_targets: "//:typecheck //:pkg //:test"
      package_dir: ./bazel-bin/pkg
      github_package_name: "@jesssullivan/scheduling-kit"
      npm_publish_mode: required
      dry_run: true
      publish_on_tag: true
    secrets: inherit
```

In that example, `PRIMARY_LINUX_RUNNER_LABELS_JSON` must resolve to a
capability-shaped label set such as `["self-hosted","linux","tinyland-nix"]`
or `["self-hosted","linux","great-falls-tool-bus-nix"]`.
It must not resolve to a known repo-label fossil. Pull-request validation remains
safe for forks because publish jobs are still gated by tag/workflow policy and
GitHub does not expose protected publish secrets to untrusted fork PRs.

## Example: capability-class template consumer

```yaml
on:
  push:
    tags: ['v*']
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v3.0.0
    with:
      runner_mode: repo_owned
      runner_labels_json: '["tinyland-nix"]'
      workspace_mode: isolated
      # publish_mode defaults to same_runner; hosted_exception is retired
      lint_command: pnpm lint
      typecheck_command: pnpm typecheck
      unit_test_command: pnpm test
      build_command: pnpm build
      bazel_targets: "//:pkg"
      package_dir: ./bazel-bin/pkg
      github_package_name: "@tinyland-inc/tinyland-auth-redis"
      npm_publish_mode: disabled
      dry_run: true
      publish_on_tag: true
```

## Notes

- `compat` exists only to let existing consumers adopt the new template without
  breaking in one PR.
- `runner_mode=repo_owned` must pass explicit `runner_labels_json` and that
  label set must include an org capability-class label. It does not authorize
  known repo-label fossils.
- `runner_mode=shared` uses `shared_runner_labels_json`. The workflow resolves
  the selected labels in a small `resolve-runner` setup job, then passes simple
  JSON outputs into `runs-on` to avoid the complex inline expressions that
  previously caused GitHub Actions startup failures before jobs were created.
  Since TIN-3914 that setup job itself runs on `tinyland-nix`: it is on the
  critical path of every invocation, so leaving it hosted would have kept a
  GitHub-hosted runner in every run.
- `runner_mode=shared` rejects an explicitly empty `shared_runner_labels_json`.
  This catches missing caller repo variables before the workflow silently falls
  back to the default shared runner class.
- Package repos that need fork-safe owned capacity should prefer
  `runner_mode=repo_owned` with explicit capability-shaped
  `runner_labels_json`. Packages that do not need cluster-internal REAPI access
  yet should use `compat` with a base capability class rather than the retired
  `hosted` mode.
- `bazel_fetch_retry_attempts` defaults to `3` and wraps consumer-provided
  validation commands plus explicit Bazel target validation. It only retries
  when the command log matches transient Bazel external archive fetch failures,
  such as upstream GitHub release `502` responses. Deterministic compile/test
  failures are not retried.
- every mode now rejects a GitHub-hosted label in `runner_labels_json` /
  `shared_runner_labels_json`, including `compat`, where labels were previously
  unvalidated. There is no hosted lane left to degrade to, so a hosted label is
  a routing error, not a fallback.
- `dry_run: true` keeps pull requests and branch pushes in validation-only mode.
  Set `publish_on_tag: true` in package repositories that should publish the
  Bazel artifact when the caller workflow is triggered by a `push` to `refs/tags/v*`.
  The caller workflow must include an `on.push.tags` trigger. npmjs publication
  requires `secrets.NPM_TOKEN` only when `npm_publish_mode=required`; Bazel-first
  packages should use `optional` or `disabled` when GitHub Packages and the
  Bazel registry are the release authority.
- self-hosted jobs now call `nix-setup`, so Attic and Bazel cache hints are
  explicit instead of incidental runner state.
- `workspace_mode=isolated` is the preferred contract for downstream pilots.
- `cleanup_paths` is still available, but only applies to
  `workspace_mode=persistent_compat`.
- publish jobs always extract into an isolated temp directory, even when the
  validation workspace stays in compatibility mode.
- npmjs publication requests provenance only off self-hosted runners. Since
  TIN-3914 every publish is self-hosted, so provenance is never requested and
  `npm_publish_provenance` is inert; the job warns instead of dropping the claim
  silently.
- real publish jobs are idempotent for already-published package versions. After
  extracting the Bazel artifact, the npmjs and GitHub Packages jobs check
  whether the exact `name@version` already exists in the target registry and
  skip only that duplicate-version case. Registry lookup failures or absent
  versions still fall through to `npm publish` so permission and package errors
  remain visible unless `npm_publish_mode=optional`.
- npm publish dry-run validation also treats npm's duplicate-version rejection
  as an idempotent pass. Newer npm versions may reject `npm publish --dry-run`
  for an already-published version even though the preceding `npm pack`
  validation proved the package artifact shape. Use `npm_publish_mode=disabled`
  to skip npmjs dry-run validation entirely for Bazel-first packages with no
  npmjs release target.
