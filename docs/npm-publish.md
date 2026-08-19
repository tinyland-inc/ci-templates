# NPM Publish Workflow

`npm-publish.yml` is the reusable workflow for straightforward Node package
build, test, and publish flows that publish directly from the workspace tree.

Unlike `js-bazel-package.yml`, this reusable workflow exposes no runner modes
at all, and it has no repository-local push-tag or manual trigger. Publishing
happens only when an existing consumer explicitly calls the pinned workflow.

## What it does

- validates the package on a matrix of Node versions
- installs dependencies with pnpm
- runs `pnpm build`
- runs `pnpm test` when a `test` script exists, but does not fail the workflow
  if tests fail
- verifies that `npm pack --dry-run` does not include source maps
- publishes to GitHub Packages when a reusable caller runs on a tag
- publishes to npmjs with provenance when a reusable caller runs on a tag

## Contract inputs

### `node-versions`

JSON array of Node versions used in the build and test matrix.

Default:

- `["20", "22"]`

### `publish-node-version`

Node version used by the publish jobs.

Default:

- `"22"`

### `pnpm-version`

pnpm version to install.

Default:

- `"9"`

### `registry-url`

npm registry URL used by the npm publish job.

Default:

- `"https://registry.npmjs.org"`

## Secrets

### `NPM_TOKEN`

Optional npmjs publish token used by the npm publish job.

GitHub Packages publish uses the built-in `GITHUB_TOKEN`.

## Execution model

Current jobs:

- `build-and-test`
- `publish-gpr`
- `publish-npm`

All three jobs run on:

- `tinyland-nix`

TIN-3914 (`v3.0.0`) moved them off GitHub-hosted runners; the estate runs only
on GF cache-fronted self-hosted runners. The label is a literal rather than a
new caller-facing input because the 2026-08-19 fleet sweep found zero callers of
this template — adding a routing contract for nobody would be inventing an
interface. A tenant org that adopts this workflow and cannot reach
`tinyland-nix` should file for the input rather than reintroduce a hosted lane.
`actions/setup-node` and `pnpm/action-setup` provision their own toolchains on
the self-hosted class, so no Nix devshell wiring was added.

Note that `publish-npm`'s provenance request now depends on the runner
environment the same way `js-bazel-package.yml`'s does; see
[`migration-v2-to-v3.md`](migration-v2-to-v3.md).

The ci-templates repository does not invoke this workflow when an immutable
workflow-library release is tagged.

## Example

```yaml
jobs:
  publish:
    uses: tinyland-inc/ci-templates/.github/workflows/npm-publish.yml@v2.0.0
    with:
      node-versions: '["20", "22"]'
      publish-node-version: "22"
      pnpm-version: "9"
      registry-url: "https://registry.npmjs.org"
    secrets:
      NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
```

## Notes

- This workflow publishes from the workspace tree, not from a Bazel-built
  extracted artifact.
- Tests are advisory today: the workflow warns if `pnpm test` fails but
  continues.
- If a package needs explicit runner policy, isolated workspaces, or publish
  authority control, use `js-bazel-package.yml` instead.
