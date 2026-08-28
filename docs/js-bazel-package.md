# JS Bzlmod Package Workflow

`js-bazel-package.yml` proves a JavaScript/TypeScript package's Bazel graph.
Its release authority is Bzlmod plus the append-only Bazel Central Registry.

> **Authority boundary:** BCR is the only package publication authority for this
> next-major lane. The workflow does not publish to npmjs or GitHub Packages,
> accept their tokens, or mutate BCR. A release is an immutable source
> tag/archive plus a separately reviewed BCR append.

## Execution contract

The workflow has one execution input: `bazel_targets` (default `//:pkg`).
GF/Nix must provide `bazelisk` on `PATH`; `command -v bazelisk` fails
closed before graph work. There is no `npx` fallback.

The workflow does not install Node or pnpm and does not accept arbitrary
prepare, lint, typecheck, test, build, or package commands. Consumer
`pnpm-lock.yaml`, rules_js, `npm_translate_lock`, and generated JS trees may
still exist inside `MODULE.bazel` / `BUILD.bazel`; Bazel owns their execution.

Every job uses a GF self-hosted capability class. `runner_mode` accepts
`compat`, `shared`, or `repo_owned`; `hosted` remains rejected.

- `compat` uses `runner_labels_json`, defaulting to `["tinyland-nix"]`.
- `shared` requires non-empty `shared_runner_labels_json`.
- `repo_owned` requires explicit `runner_labels_json`.

`repo_owned` is a trust and registration boundary. The workflow-facing labels
still stay org capability classes; isolation belongs in ARC registration,
runner groups, GitHub App installation, and the implementation overlay. It must
not resolve to a known repo-label fossil.

Pull-request validation remains safe for forks because this workflow has no
registry publication job or publish credential. Source-tag and BCR transactions
remain separate attended operations.

## Workspace and credentials

Validation always copies the clean checkout into one isolated
`$RUNNER_TEMP` workspace. The workflow accepts only
`TINYLAND_REGISTRY_GITHUB_TOKEN`, a read credential for private module source
archives; absent that secret it uses `github.token`. No registry write token is
declared.

## Bzlmod lock controls

`verify_bzlmod_lock` and `emit_bzlmod_lock_artifact` are independent,
default-off inputs.

- verification requires a clean tracked root lock, refreshes with
  `bazelisk mod deps --lockfile_mode=update`, fails on drift, and validates
  targets with `--lockfile_mode=error`
- emission may create or refresh the lock and uploads it once as
  `bzlmod-lock`

The artifact is review evidence only; the workflow never commits caller bytes.

## Cache-backed validation

`cache_backed` is default-off. When enabled, the workflow validates
`tinyland.repo.json`, resolves expected mode from
`enrollment.substrateMode`, runs
`scripts/cache-attachment-contract.sh --strict`, and reads
`--config=ci-cached --remote_cache=$BAZEL_REMOTE_CACHE
--remote_upload_local_results=false`. This is cache-first only; no remote
executor is wired.

## Example v4 caller

The v4 tag does not exist until the attended immutable release completes. After
that release, pin the exact version:

```yaml
jobs:
  package:
    uses: tinyland-inc/ci-templates/.github/workflows/js-bazel-package.yml@v4.0.0
    with:
      runner_mode: repo_owned
      runner_labels_json: '["tinyland-nix"]'
      bazel_targets: "//:typecheck //:pkg //:test"
      verify_bzlmod_lock: true
      cache_backed: true
    secrets:
      TINYLAND_REGISTRY_GITHUB_TOKEN: ${{ secrets.TINYLAND_REGISTRY_GITHUB_TOKEN }}
```

Tag/release creation, archive verification, and BCR append remain outside this
workflow. See [`migration-v3-to-v4.md`](migration-v3-to-v4.md). Exact v3 tags
remain immutable until each consumer deliberately changes its pin.
