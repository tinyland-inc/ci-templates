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

See [docs/js-bazel-package.md](./docs/js-bazel-package.md) for usage and inputs.

## Requirements

- **Self-hosted runners:** Attic and Bazel cache auto-detected via cluster DNS
- **GitHub-hosted runners:** Pass `attic-server` input explicitly
- **Secrets:** `ATTIC_TOKEN` for cache push operations
