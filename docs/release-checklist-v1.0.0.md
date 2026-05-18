# Release checklist: ci-templates v1.0.0

> **Status**: Pre-release. All v1.0.0 work has landed on
> `feat/v1.0.0`; this checklist is the operator-facing
> sequence for cutting the actual release.
>
> **Why this doc exists**: per [`RELEASING.md`](../RELEASING.md), tags
> are cut on `main` after the release commit lands. The `release.yml`
> workflow validates this: it asserts the head commit subject is
> `release: vX.Y.Z` before tagging. Cutting tags from a feature
> branch would bypass that contract.

## Pre-flight

- [ ] `feat/v1.0.0` is green in CI (when ci-templates' own CI runs
      against it).
- [ ] Two ci-templates commits are present on `feat/v1.0.0`:
  - `7e5dae0` — spoke CI / lane-env / pulse-ingest surface.
  - `92007a4` — release workflow + nix-setup/secrets-scan refactors.
  - `80d5e86` — dev-remote v1.1+ design doc.
- [ ] Companion repos have their changes committed:
  - `tinyland-inc/site.scaffold` `feat/ci-schema-d1` → `b3bf06e`.
  - `tinyland-inc/GloriousFlywheel` `feat/spoke-tofu-modules` →
    `721af25` (branched off `jess/sprint-may-10-jess-stream`).
  - `tinyland-inc/.github` `feat/spoke-default-ruleset` →
    `11b3623`.

## Step 1 — Cut the retroactive v0.4.0 baseline

Gives existing `@main` consumers a stable pin to migrate from per
[`docs/migration-v0-to-v1.md`](./migration-v0-to-v1.md).

```bash
cd ~/git/ci-templates
git checkout main
# main HEAD is currently d202fc0 (Merge pull request #27 ...).
# That's the pre-v1.0.0 baseline.
git tag -a v0.4.0 -m "v0.4.0 (retroactive baseline of @main pre-v1.0.0)"
git push origin v0.4.0
```

Verify:

```bash
gh release create v0.4.0 \
  --title "v0.4.0 (retroactive baseline)" \
  --notes "Snapshot of @main at the SHA preceding the v1.0.0 cut. Provided so consumers on @main have a SemVer tag to pin against during migration. No code changes from the pre-tag @main state."
```

## Step 2 — Merge `feat/v1.0.0` to `main`

Two options; pick the one that matches your operator preference.

### Option 2a — PR + merge (recommended for shared review)

```bash
cd ~/git/ci-templates
git push -u origin feat/v1.0.0

gh pr create \
  --base main \
  --head feat/v1.0.0 \
  --title "feat: v1.0.0 — spoke CI / lane-env / pulse-ingest reusable surface" \
  --body-file - <<'EOF'
## Summary

First versioned release. See [CHANGELOG.md](./CHANGELOG.md) for the
full v1.0.0 entry and [RELEASING.md](./RELEASING.md) for the release
flow this PR concludes.

## Test plan

- [ ] All composite-action YAML parses (`ruby -ryaml -e ...`).
- [ ] Schemas validate against draft-2020-12.
- [ ] At least one spoke (start with `tinyland-inc/site.scaffold`)
      consumes a pinned `@v1.0.0` reference and is green.

## Companion changes

- `tinyland-inc/site.scaffold` PR consuming `@v1.0.0` (branch
  `feat/ci-schema-d1`).
- `tinyland-inc/GloriousFlywheel` PR adding spoke-* Tofu modules
  (branch `feat/spoke-tofu-modules`).
- `tinyland-inc/.github` PR adding the org-default ruleset (branch
  `feat/spoke-default-ruleset`).
EOF

# After review, merge with --squash so main gets one clean commit.
gh pr merge --squash --delete-branch
```

The squash commit on `main` becomes the `v1.0.0` tag target.

### Option 2b — local merge (skip PR review)

```bash
cd ~/git/ci-templates
git checkout main
git merge --squash feat/v1.0.0
git commit -m "feat: v1.0.0 — spoke CI / lane-env / pulse-ingest reusable surface"
git push origin main
git branch -D feat/v1.0.0
git push origin :feat/v1.0.0  # if you pushed it earlier
```

## Step 3 — Cut `v1.0.0` (and let `release.yml` automate)

The `release.yml` workflow added in `92007a4` auto-cuts the tag if you
push a commit titled `release: vX.Y.Z`. Take advantage:

```bash
cd ~/git/ci-templates
git checkout main
git pull --ff-only

# Move "## [Unreleased]" content to "## [1.0.0] — <date>" if not
# already done. (For v1.0.0 specifically, the section already exists.)
# Verify CHANGELOG.md has a `## [1.0.0]` heading.

git commit --allow-empty -m "release: v1.0.0"
git push origin main
```

`release.yml`'s `tag-on-release-commit` job will:

1. Detect the `release: v1.0.0` subject.
2. Verify the tag doesn't already exist.
3. Verify `CHANGELOG.md` has `## [1.0.0]`.
4. Tag `v1.0.0` (immutable) and `v1` (floating major).
5. Push both tags.
6. Create the GitHub Release with notes extracted from
   `CHANGELOG.md`'s `## [1.0.0]` section.

Watch the run:

```bash
gh run watch
```

## Step 4 — Verify

```bash
# Tags exist
gh release view v1.0.0
gh api /repos/tinyland-inc/ci-templates/git/refs/tags/v1.0.0
gh api /repos/tinyland-inc/ci-templates/git/refs/tags/v1

# At least one spoke can consume the pin
cd ~/git/site.scaffold
git checkout feat/ci-schema-d1
just lanes-validate && just conformance
# After tag exists, `@v1.0.0` in .github/workflows/*.yml resolves.
```

## Step 5 — Tag GloriousFlywheel's spoke modules separately

`site.scaffold/tofu/main.tf` currently references
`git::ssh://...//tofu/modules/spoke-state-namespace?ref=v1.0.0`. That
`v1.0.0` is a placeholder — GloriousFlywheel has its own product
versioning, and we should NOT tag the whole repo `v1.0.0` from spoke
work.

**Recommended**: cut a scoped tag like `spoke-tofu-modules-v1.0.0`
covering only the spoke-* module additions:

```bash
cd ~/git/GloriousFlywheel
git checkout feat/spoke-tofu-modules
git tag -a spoke-tofu-modules-v1.0.0 -m "Spoke Tofu modules v1.0.0"
git push origin spoke-tofu-modules-v1.0.0
```

Then update `site.scaffold/tofu/main.tf`:

```diff
-  modules_ref       = "v1.0.0" # bump when GloriousFlywheel cuts a new tag
+  modules_ref       = "spoke-tofu-modules-v1.0.0"
```

Land that update as a follow-up PR on `site.scaffold` after the spoke
modules merge to GloriousFlywheel's `main` (which is gated on your
`jess/sprint-may-10-jess-stream` work landing first — coordinate).

## Step 6 — Org ruleset

Once `tinyland-inc/.github`'s `feat/spoke-default-ruleset` is merged,
apply the ruleset to each existing spoke:

```bash
for spoke in site.scaffold elders.tinyland.dev gear.tinyland.dev darkmap.tinyland.dev; do
  gh api \
    /repos/tinyland-inc/${spoke}/rulesets \
    -X POST \
    --input <(curl -s https://raw.githubusercontent.com/tinyland-inc/.github/main/.github/rulesets/tinyland-spoke-default.json)
done
```

Verify with `gh api /repos/tinyland-inc/<spoke>/rulesets`.

## Rollback (if v1.0.0 is botched)

Per RELEASING.md: **never delete a tag, never reuse a tag**. If the
v1.0.0 cut goes wrong:

1. Identify the bug.
2. Fix on `main` via a normal PR.
3. Cut `v1.0.1` via the same `release: v1.0.1` commit pattern.
4. Spokes bump their `@v1.0.0` pin to `@v1.0.1`.

The `@v1` floating tag will move forward automatically when `v1.0.1`
is cut, so consumers on the floating tag get the fix without action.

## What this checklist does NOT cover

- Pushing branches to `origin` — that's an explicit operator step
  (none of this work has been pushed yet).
- Org ruleset application beyond `tinyland-inc/.github`'s side —
  spoke owners run the `gh api .../rulesets` calls.
- Blahaj-side configuration for spokes consuming the new lane
  workflows — separate repo, separate operator track.
