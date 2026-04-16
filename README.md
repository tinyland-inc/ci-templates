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

### `bazel-js-verify`

Blocking workspace + Bazel verification for JS packages that treat `//:pkg` as package truth.

```yaml
jobs:
  verify:
    uses: tinyland-inc/ci-templates/.github/workflows/bazel-js-verify.yml@main
    with:
      metadata_command: "node scripts/check-release-metadata.mjs"
      check_command: "pnpm check"
      lint_command: "pnpm lint"
      unit_test_command: "pnpm test:unit"
      integration_test_command: "pnpm test:integration"
      build_command: "pnpm build"
      package_check_command: "pnpm exec publint"
      bazel_build_command: "npx --yes @bazel/bazelisk build //:pkg //:typecheck //:test --verbose_failures"
      bazel_package_path: "./bazel-bin/pkg"
```

### `bazel-js-publish`

Builds the Bazel package artifact once, uploads it, and publishes that exact artifact to npm and optionally GitHub Packages.

```yaml
jobs:
  publish:
    uses: tinyland-inc/ci-templates/.github/workflows/bazel-js-publish.yml@main
    secrets:
      NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
    with:
      metadata_command: "node scripts/check-release-metadata.mjs"
      test_command: "pnpm test:unit"
      build_command: "pnpm build"
      package_check_command: "pnpm exec publint"
      bazel_build_command: "npx --yes @bazel/bazelisk build //:pkg //:typecheck //:test --verbose_failures"
      bazel_package_path: "./bazel-bin/pkg"
      publish_dry_run: false
      publish_to_github_packages: true
      github_package_name: "@jesssullivan/scheduling-kit"
```

`bazel-js-publish` always validates the Bazel-built package with `npm pack --dry-run` and `npm publish --dry-run --ignore-scripts` before any real publish step. Real publish also uses `--ignore-scripts` because the scripts have already been exercised before the artifact is archived.

## Requirements

- **Self-hosted runners:** Attic and Bazel cache auto-detected via cluster DNS
- **GitHub-hosted runners:** Pass `attic-server` input explicitly
- **Secrets:** `ATTIC_TOKEN` for cache push operations
