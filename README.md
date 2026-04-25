# ci-templates

Reusable GitHub Actions composite actions for tinyland-inc CI/CD.

## Actions

### `nix-setup`

Configure Nix and cache endpoints. Auto-detects Attic and Bazel on self-hosted ARC runners via cluster DNS.

```yaml
- uses: tinyland-inc/ci-templates/.github/actions/nix-setup@main
  with:
    attic-cache: "main"  # optional, default: main
```

### `nix-build`

Run Nix build with Attic binary cache. Installs Nix, configures caches, runs command.

```yaml
- uses: tinyland-inc/ci-templates/.github/actions/nix-build@main
  with:
    command: "nix build .#package"
    push-cache: "true"
  env:
    ATTIC_TOKEN: ${{ secrets.ATTIC_TOKEN }}
```

### `greedy-cache`

Start Attic `watch-store` daemon for concurrent binary cache push. Derivations are pushed as they build, not after.

```yaml
- uses: tinyland-inc/ci-templates/.github/actions/greedy-cache@main
  with:
    attic-cache: "tinyland-lab"
    watch-jobs: "8"
  env:
    ATTIC_TOKEN: ${{ secrets.ATTIC_TOKEN }}

- run: nix build .#package  # derivations pushed concurrently as they build
```

### `secrets-scan`

TruffleHog (verified secrets) + Gitleaks detection.

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: tinyland-inc/ci-templates/.github/actions/secrets-scan@main
```

## Reusable Workflows

### `js-bazel-package`

Reusable workflow for JS/TS packages whose release artifact is built by Bazel and then published to npm or GitHub Packages.

Supports explicit runner policy (`compat`, `hosted`, `shared`, `repo_owned`), explicit workspace policy (`isolated`, `persistent_compat`), explicit publish policy (`same_runner`, `hosted_exception`), self-hosted cache contract wiring, optional advisory lint/typecheck lanes, Bazel-artifact dry-runs, and npm/GitHub Packages publication from the extracted Bazel package.

The Bazel validation step includes bounded retries for transient external
archive fetch failures, so package repos do not each vendor ad hoc GitHub
release-download retry logic.

See [docs/js-bazel-package.md](./docs/js-bazel-package.md) for usage and inputs.

### `npm-publish`

Reusable workflow for straightforward Node package build, test, and publish
flows that publish directly from the workspace tree.

Current behavior:

- hosted-only on `ubuntu-latest`
- build and advisory test on a Node version matrix
- publish to GitHub Packages and npmjs on tags

See [docs/npm-publish.md](./docs/npm-publish.md) for usage and inputs.

## Requirements

- **Self-hosted runners:** Attic and Bazel cache auto-detected via cluster DNS
- **GitHub-hosted runners:** Pass `attic-server` input explicitly
- **Secrets:** `ATTIC_TOKEN` for cache push operations
