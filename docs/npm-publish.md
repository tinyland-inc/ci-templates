# NPM Publish Workflow

`npm-publish.yml` is the reusable workflow for straightforward Node package
build, test, and publish flows that publish directly from the workspace tree.

Unlike `js-bazel-package.yml`, this workflow is currently GitHub-hosted only.
It does not expose shared-runner or repo-owned runner modes.

## What it does

- validates the package on a matrix of Node versions
- installs dependencies with pnpm
- runs `pnpm build`
- runs `pnpm test` when a `test` script exists, but does not fail the workflow
  if tests fail
- verifies that `npm pack --dry-run` does not include source maps
- publishes to GitHub Packages on tags
- publishes to npmjs with provenance on tags

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

All three jobs currently run on:

- `ubuntu-latest`

This is a hosted-only workflow today.

## Example

```yaml
jobs:
  publish:
    uses: tinyland-inc/ci-templates/.github/workflows/npm-publish.yml@main
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
