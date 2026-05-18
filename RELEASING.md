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
3. **Cut the release**:
   ```bash
   ver=v1.2.3
   sed -i "s|## \[Unreleased\]|## [Unreleased]\n\n## [${ver#v}] — $(date -u +%Y-%m-%d)|" CHANGELOG.md
   git add CHANGELOG.md
   git commit -m "release: $ver"
   git tag -a "$ver" -m "$ver"
   # Move the floating major tag too
   git tag -f -a "v${ver%%.*}" -m "track $ver"
   git push origin main "$ver" "v${ver%%.*}" --force-with-lease
   gh release create "$ver" --title "$ver" --notes-from-tag
   ```
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

Composite actions that nest other composites (e.g. `flywheel-bazel`
calling `nix-setup`) MUST reference siblings by major tag, not `@main`:

```yaml
uses: tinyland-inc/ci-templates/.github/actions/nix-setup@v1
```

This ensures a `git checkout v1.2.3` of the repo exposes a coherent
self-referential set of action versions.
