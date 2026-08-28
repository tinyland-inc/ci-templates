# Migration from v3 to v4

v4 makes `js-bazel-package.yml` a Bzlmod/BCR graph-proof lane. This is a MAJOR
because publication surfaces and arbitrary workspace command surfaces disappear.

Exact v3 tags and immutable v3.1.0 remain unchanged. Nothing here bulk-migrates
a consumer, moves a tag, publishes a release, or edits a consumer repository.

## Removed interface

Remove these provider-era keys: `publish_mode`, `publish_node_version`,
`package_dir`, `npm_access`, `npm_publish_provenance`,
`npm_publish_mode`, `npm_registry_url`, `github_package_name`,
`github_package_registry`, `dry_run`, and `publish_on_tag`.

Also remove the legacy task-runner keys: `node_versions`, `pnpm_version`,
`workspace_mode`, `cleanup_paths`, `metadata_check_command`,
`prepare_command`, `lint_command`, `lint_continue_on_error`,
`typecheck_command`, `typecheck_continue_on_error`, `unit_test_command`,
`integration_test_command`, `build_command`, and
`package_check_command`. Express those checks as Bazel targets and pass only
`bazel_targets`.

The reusable workflow no longer declares `NPM_TOKEN`,
`TINYLAND_GITHUB_PACKAGES_TOKEN`, `SYNC_PAT`, or `GH_TOKEN`; no
`publish-npm` / `publish-github` job, registry dry-run, package rewrite,
npm-shaped artifact, Node setup, pnpm install, or tag-triggered publication
remains.

At the caller, remove provider write secrets and `packages: write`; retain only
`contents: read` plus `TINYLAND_REGISTRY_GITHUB_TOKEN` when private module
source archives require it.

The standalone `npm-publish.yml` is removed. The authenticated 2026-08-27
census found no callers in `tinyland-inc` or `Jesssullivan`; its own guide
was the only tinyland-inc match.

## Preserved module mechanics

This is not a ban on JS dependency resolution inside Bazel. A consumer may keep
`pnpm-lock.yaml`, rules_js, `npm_translate_lock`, and generated JS package
trees in `MODULE.bazel` / `BUILD.bazel`. Bazel evaluates that graph; the
shared workflow no longer runs arbitrary pnpm commands around it.

The `npx --yes @bazel/bazelisk` fallback is removed. GF/Nix must provide
`bazelisk` on `PATH`; absence fails closed.

## Release sequence

1. land reviewed `MODULE.bazel`, version metadata, and lock evidence
2. obtain exact-source GF graph proof
3. create the signed immutable source tag/release through the source runbook
4. verify archive identity and digest
5. append through reviewed BCR and prove clean consumer resolution

No step publishes an npm package, rewrites v3, or infers release authority from
a green build.
