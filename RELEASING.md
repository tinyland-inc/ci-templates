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
      read
   5. move the floating major last, with Contents write

   An interrupted run is retryable only when an existing exact tag peels to the
   same source and an existing Release is published, non-prerelease, and
   tag-matched. Conflicts fail closed; the floating major cannot move before
   published verification.

   ```bash
   ver=v1.2.3
   sed -i "s|## \[Unreleased\]|## [Unreleased]\n\n## [${ver#v}] — $(date -u +%Y-%m-%d)|" CHANGELOG.md
   git add CHANGELOG.md
   git commit -m "release: $ver"
   git push origin main
   # release.yml fires; publishes/verifies $ver, then moves @vMAJOR last.
   ```

   ### 3b. Manual fallback

   Use when 3a's "push to main" doesn't work in your environment:

   - **Push-protection hook on `main`** (e.g. local agent safety hook
     blocking direct push to `main` and/or `release/*` branches —
     surfaced during darkmap's v1.0.0 cut).
   - **GitHub rebase-merge drops empty commits**, so a
     `git commit --allow-empty -m "release: vX.Y.Z"` pushed to a
     feature branch and rebase-merged into main yields a main HEAD
     without the release subject — `release.yml` doesn't fire.

   Manual cut follows the same order. Mint a short-lived Administration-read
   installation token through the approved operator App/broker path into a
   local shell variable without printing it. The normal authenticated `gh`
   token supplies Contents reads/writes.

   ```bash
   ver=v1.2.3
   major="${ver%%.*}"
   target_sha=$(git rev-parse origin/main)   # or a specific merge SHA

   # Make sure CHANGELOG.md already has the ## [X.Y.Z] section.
   # If not, land that via a normal PR first.
   grep -qE "^## \\[${ver#v}\\]" CHANGELOG.md || {
     echo "CHANGELOG.md missing ## [${ver#v}] section — land that PR first"
     exit 1
   }

   # Before any tag or Release mutation:
   IMMUTABLE_RELEASE_MODE=settings \
   IMMUTABLE_RELEASE_REPOSITORY=tinyland-inc/ci-templates \
   IMMUTABLE_RELEASE_ADMIN_TOKEN="$admin_token" \
   scripts/immutable-release-verify.sh
   unset admin_token

   git tag -a "$ver" "$target_sha" -m "$ver

   See CHANGELOG.md ## [${ver#v}] for the full Added/Changed list."
   git push origin "$ver"

   # Extract just this version's CHANGELOG section for the GH Release:
   awk -v v="${ver#v}" '
     $0 ~ "^## \\[" v "\\]" {flag=1; next}
     /^## \[/ && flag {exit}
     flag {print}
   ' CHANGELOG.md > /tmp/release-notes.md

   gh release create "$ver" \
     --verify-tag \
     --target "$target_sha" \
     --title "$ver" \
     --notes-file /tmp/release-notes.md

   IMMUTABLE_RELEASE_MODE=published \
   IMMUTABLE_RELEASE_REPOSITORY=tinyland-inc/ci-templates \
   IMMUTABLE_RELEASE_TAG="$ver" \
   IMMUTABLE_RELEASE_EXPECTED_SOURCE_SHA="$target_sha" \
   IMMUTABLE_RELEASE_CONTENTS_TOKEN="$GH_TOKEN" \
   scripts/immutable-release-verify.sh

   git tag -f -a "$major" "$target_sha" -m "track $ver"
   git push origin "$major" --force-with-lease
   ```

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

The privileged `immutable-release-verify` calls are the deliberate exception:
they pin a full commit SHA so code receiving the Administration token or
release-read token cannot move with `@v2`. Update both pinned calls together
only after reviewing and committing the verifier implementation first.

## Flywheel endpoint discipline

`bazelrc/flywheel.bazelrc` MUST remain endpoint-free. Release checks should
reject hard-coded `remote_cache`, `remote_executor`, credentials, headers, or
cache upload authority in that fragment. Runtime authority belongs in
`BAZEL_REMOTE_CACHE`, `BAZEL_REMOTE_EXECUTOR`, optional auth/header env vars,
and `GF_BAZEL_REMOTE_UPLOAD`.
