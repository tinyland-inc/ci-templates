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

1. **Land all changes for the release on `main`** via squash-merged PRs.
   Each PR amends `## [Unreleased]` in `CHANGELOG.md`.
2. **Pick the next version** per SemVer:
   - **MAJOR** — breaking changes to composite-action inputs, reusable
     workflow inputs/secrets interface, schema major bumps.
   - **MINOR** — new actions / workflows, new optional inputs, schema
     minor bumps.
   - **PATCH** — bug fixes, prose/doc updates, internal refactors.
3. **Land the release commit through a normal PR.** Move the complete
   `## [Unreleased]` body into `## [X.Y.Z] — YYYY-MM-DD`, restore an empty
   `## [Unreleased]`, and use subject `release: vX.Y.Z`. Do not push directly
   to `main`. If a restricted workflow needs composites changed by this
   release, its self-references must name this exact version before the release
   commit lands; an exact release that calls floating `@vMAJOR` is not
   immutable in practice.
4. **Enable native immutable releases before publishing.** This setting affects
   future releases only:

   ```bash
   gh api --method PUT \
     -H 'X-GitHub-Api-Version: 2026-03-10' \
     repos/tinyland-inc/ci-templates/immutable-releases
   ```

5. **Prove the dependency closure offline, then cut signed tags with an exact
   floating-tag lease.** `just check` must pass from the exact release commit.
   The restricted closure check recursively resolves every internal composite,
   requires exact self-release refs and full third-party commit SHAs, and
   verifies that downloaded scanner archives have source-pinned SHA-256 values.
   Never move or reuse the
   exact SemVer tag. The floating major is intentionally advanced:

   ```bash
   ver=v1.2.3
   major="${ver%%.*}"
   target_sha="$(git rev-parse origin/main)"
   old_major_ref="$(git ls-remote --tags origin "refs/tags/$major" | awk '{print $1}')"

   grep -qE "^## \\[${ver#v}\\]" CHANGELOG.md || {
     echo "CHANGELOG.md missing ## [${ver#v}] — land the release PR first"
     exit 1
   }

   git tag -s "$ver" "$target_sha" -m "$ver"
   git tag -f -s "$major" "$target_sha" -m "track $ver"
   git push --atomic origin "refs/tags/$ver" "refs/tags/$major" \
     --force-with-lease="refs/tags/$major:$old_major_ref"
   ```

6. **Publish and verify the immutable GitHub release.** Draft first, inspect the
   notes, then publish. Publication locks the exact release tag and produces the
   release attestation:

   ```bash
   notes_file="$(mktemp -t ci-templates-release-notes.XXXXXX)"
   trap 'rm -f "$notes_file"' EXIT
   awk -v v="${ver#v}" '
     $0 ~ "^## \\[" v "\\]" {flag=1; next}
     /^## \[/ && flag {exit}
     flag {print}
   ' CHANGELOG.md > "$notes_file"

   gh release create "$ver" --verify-tag --draft \
     --title "$ver" --notes-file "$notes_file"
   gh release edit "$ver" --draft=false
   gh api "repos/tinyland-inc/ci-templates/releases/tags/$ver" --jq .immutable
   gh release verify "$ver"
   ```

7. **Verify a consumer pin**: at least one spoke
   (`tinyland-inc/site.scaffold` first) pins the exact `@vX.Y.Z` release and its
   sanctioned private-group checks report the expected non-Default group.

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

The restricted private-runner reusable workflows and every sibling composite in
their transitive closure MUST reference siblings by an exact immutable release,
not `@main`, floating `@vMAJOR`, or a consumer-relative `./` path:

```yaml
uses: tinyland-inc/ci-templates/.github/actions/nix-setup@v2.12.1
```

This makes the exact workflow tag a closed source graph: moving the floating
major cannot change a pinned caller's nested actions. Third-party Actions in
that closure use full commit SHAs, and release binaries are downloaded to a
file and verified against a source-pinned checksum before execution. The
historical legacy workflows still contain floating-major self-refs and are not
evidence for the restricted immutability contract; do not copy that pattern
into a new surface.

## Flywheel endpoint discipline

`bazelrc/flywheel.bazelrc` MUST remain endpoint-free. Release checks should
reject hard-coded `remote_cache`, `remote_executor`, credentials, headers, or
cache upload authority in that fragment. Runtime authority belongs in
`BAZEL_REMOTE_CACHE`, `BAZEL_REMOTE_EXECUTOR`, optional auth/header env vars,
and `GF_BAZEL_REMOTE_UPLOAD`.
