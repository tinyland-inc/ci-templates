# Releasing `tinyland-inc/ci-templates`

This repo uses [SemVer 2.0](https://semver.org/). Spokes pin to
immutable `@vMAJOR.MINOR.PATCH` tags; **`@main` is the develop branch
and may break without notice**.

## Tag scheme

| Pin | Mutability | Audience |
|---|---|---|
| `@vMAJOR.MINOR.PATCH` | Immutable | All spokes. The documented form. |
| `@vMAJOR` | Floating to latest `vMAJOR.M.P` | Quick-start docs only; spokes nudged off it during review. |
| `@main` | Develop tip | ci-templates contributors only. **Not for spoke use.** |

## Release flow

The release workflow requires repository immutable releases to be enabled and
two App custody secrets: `IMMUTABLE_RELEASE_APP_CLIENT_ID` and
`IMMUTABLE_RELEASE_APP_PRIVATE_KEY`. It uses the approved runtime GitHub App
mint to request a repository-scoped **Administration read** installation token,
then revokes that token automatically at job teardown. Never store an
installation token, substitute an owner PAT, or grant the App package/write
authority for this check.

1. **Land all changes for the release on `main`** via squash-merged PRs.
   Each PR amends `## [Unreleased]` in `CHANGELOG.md`.
2. **Pick the next version** per SemVer:
   - **MAJOR** — breaking changes to composite-action inputs, reusable
     workflow inputs/secrets interface, schema major bumps.
   - **MINOR** — new actions / workflows, new optional inputs, schema
     minor bumps.
   - **PATCH** — bug fixes, prose/doc updates, internal refactors.
3. **Cut the release**. Pick **3a** (workflow-driven, preferred when
   it works) or **3b** (manual fallback, use when 3a's preconditions
   don't hold in your environment):

   ### 3a. Workflow-driven (preferred)

   `release.yml` detects a commit with subject `release: vX.Y.Z` on main, then
   advances authority through separate jobs:

   1. plan and validate any recoverable existing exact tag with Contents read
   2. mint the short-lived App token and check immutable-release settings with
      no `GITHUB_TOKEN` permissions
   3. create or reuse the exact version tag and published GitHub Release
   4. verify the immutable Release attestation and source binding with Contents
      read plus Attestations read
   5. move the floating major last, with Contents write

   An interrupted run is retryable only when an existing exact tag peels to the
   same source and an existing Release is published, non-prerelease, and
   tag-matched. Conflicts fail closed; the floating major cannot move before
   published verification. Workflow concurrency uses `queue: max` so a newer
   pending push does not replace an older pending release run. GitHub does not
   guarantee dispatch order, so the final step also compares semantic versions
   and refuses to move the floating major backward when an older run starts or
   is re-run later.

   ```bash
   ver=v1.2.3
   sed -i "s|## \[Unreleased\]|## [Unreleased]\n\n## [${ver#v}] — $(date -u +%Y-%m-%d)|" CHANGELOG.md
   git add CHANGELOG.md
   git commit -m "release: $ver"
   git push origin main
   # release.yml fires; publishes/verifies $ver, then moves @vMAJOR last.
   ```

   ### 3b. Manual dispatch fallback

   Use when 3a's "push to main" doesn't work in your environment:

   - **Push-protection hook on `main`** (e.g. local agent safety hook
     blocking direct push to `main` and/or `release/*` branches —
     surfaced during darkmap's v1.0.0 cut).
   - **GitHub rebase-merge drops empty commits**, so a
     `git commit --allow-empty -m "release: vX.Y.Z"` pushed to a
     feature branch and rebase-merged into main yields a main HEAD
     without the release subject — `release.yml` doesn't fire.

   Dispatch the same release workflow from `main` with the exact version. This
   is not a second implementation: it enters the same settings check, exact-tag
   and Release publication, Attestations read verification, and floating-major
   compare-and-swap jobs as 3a. No App token, tag, or Release is created from the
   operator shell.

   ```bash
   set -euo pipefail
   ver=v1.2.3
   run_url="$(
     gh workflow run release.yml \
       --repo tinyland-inc/ci-templates \
       --ref main \
       --raw-field "version=$ver"
   )"
   run_id="${run_url##*/}"
   [[ "$run_id" =~ ^[0-9]+$ ]] || {
     echo "release dispatch did not return a run URL: $run_url" >&2
     exit 1
   }
   gh run watch "$run_id" \
     --repo tinyland-inc/ci-templates \
     --compact \
     --exit-status
   ```

   The dispatch job is accepted only from `refs/heads/main`, the version input
   must match `vMAJOR.MINOR.PATCH`, and `CHANGELOG.md` at that exact main commit
   must contain the matching section. The shared floating-major step proves the
   annotation's referenced exact tag exists, belongs to the same major, and
   peels to the current `vMAJOR` commit before comparing versions. Movement uses
   the remote tag object captured by `git ls-remote` as the explicit
   `--force-with-lease=refs/tags/vMAJOR:<object>` expectation; a concurrent move
   or backward request fails closed.

   Verify with `gh release view "$ver"` and at least one downstream
   spoke bumping its `@v...` pin.

4. **Verify**: at least one spoke (`tinyland-inc/site.scaffold` first)
   bumps its `@v...` pin and CI is green.

## Migration discipline

- **Never delete a tag.** If a release was botched, cut a new patch.
- **Never reuse a tag.** v1.0.0 is v1.0.0 forever.
- The floating `@vMAJOR` tag *is* moved forward on minor/patch
  releases — that is its purpose. Spokes pinning to it accept the
  implicit minor/patch upgrade contract.
- Breaking changes that require a MAJOR bump also require a
  `docs/migration-vN-to-vN+1.md` doc and an entry in the new MAJOR's
  CHANGELOG section.

## Backporting to a previous MAJOR (e.g. v1.x after v2 ships)

1. Branch from the latest `v1.x.y` tag: `git checkout -b release/v1 v1.99.99`.
2. Cherry-pick the fix.
3. Bump version on `release/v1`, tag, push as above.
4. Update CHANGELOG on `main` noting the backport.

## Composite-action internal refs

Ordinary composite actions and reusable workflows that call sibling composites
(e.g. `flywheel-bazel` calling `nix-setup`) reference siblings by the current
major tag, not `@main` or an older major:

```yaml
uses: tinyland-inc/ci-templates/.github/actions/nix-setup@v2
```

This ensures a `git checkout v2.0.0` of the repo exposes a coherent
self-referential set of action versions. A v2 reusable workflow must not call
v1 composites unless the migration guide explicitly documents that compatibility
boundary.

The privileged `immutable-release-verify` calls are the deliberate exception.
They do not use a remote self-reference because a workflow cannot embed its own
future commit SHA without a circular update. Release jobs check out the planned
main source SHA and invoke the local verifier action. The reusable package
workflow reads its resolved workflow SHA from the authenticated run API's
`referenced_workflows` record, checks out that exact ci-templates tree, and then
invokes the local action. Validation rejects remote verifier self-pins and any
checkout that is not tied to those reviewed source SHAs.

## Flywheel endpoint discipline

`bazelrc/flywheel.bazelrc` MUST remain endpoint-free. Release checks should
reject hard-coded `remote_cache`, `remote_executor`, credentials, headers, or
cache upload authority in that fragment. Runtime authority belongs in
`BAZEL_REMOTE_CACHE`, `BAZEL_REMOTE_EXECUTOR`, optional auth/header env vars,
and `GF_BAZEL_REMOTE_UPLOAD`.
