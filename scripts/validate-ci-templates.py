#!/usr/bin/env python3
"""Repository-local validation helpers for tinyland-inc/ci-templates."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def validate_manifest() -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("python jsonschema is unavailable", file=sys.stderr)
        return 2

    schema_path = ROOT / "schemas/tinyland-repo-manifest.schema.json"
    manifest_path = ROOT / "tinyland.repo.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        for err in errors:
            path = "/" + "/".join(str(p) for p in err.absolute_path)
            print(f"{manifest_path.relative_to(ROOT)} {path}: {err.message}", file=sys.stderr)
        return 1
    print("tinyland.repo.json valid")
    return 0


def check_internal_refs() -> int:
    ok = True
    action_pattern = re.compile(
        r"tinyland-inc/ci-templates/\.github/actions/([^@\s]+)@([^\s#]+)"
    )
    main_pattern = re.compile(r"tinyland-inc/ci-templates/.*@main")
    full_sha_pattern = re.compile(r"[0-9a-f]{40}")

    for path in sorted((ROOT / ".github").glob("**/*.yml")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for action, ref in action_pattern.findall(text):
            action_yml = ROOT / ".github/actions" / action / "action.yml"
            if not action_yml.exists():
                print(f"{rel}: missing internal action {action_yml.relative_to(ROOT)}", file=sys.stderr)
                ok = False
            if action == "immutable-release-verify":
                if not full_sha_pattern.fullmatch(ref):
                    print(
                        f"{rel}: privileged immutable-release verifier must use a full commit SHA, got @{ref}",
                        file=sys.stderr,
                    )
                    ok = False
            elif ref != "v2":
                print(
                    f"{rel}: internal action {action} must use the coherent @v2 ref, got @{ref}",
                    file=sys.stderr,
                )
                ok = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            if main_pattern.search(line):
                print(f"{rel}:{line_no}: internal ci-templates ref uses @main", file=sys.stderr)
                ok = False

    if not ok:
        return 1
    print("internal action refs resolve")
    return 0


def check_js_bazel_package_runner_contract() -> int:
    workflow_path = ROOT / ".github/workflows/js-bazel-package.yml"
    docs_path = ROOT / "docs/js-bazel-package.md"
    workflow = workflow_path.read_text(encoding="utf-8")
    docs = docs_path.read_text(encoding="utf-8")

    required_workflow_snippets = [
        "runner_mode=repo_owned requires explicit runner_labels_json",
        "must include an org capability-class label",
        "org_capability_label = re.compile",
        "nix|nix-heavy|nix-kvm|nix-gpu|docker|dind",
        '"tinyland-docker"',
        "runner_mode=shared requires shared_runner_labels_json",
    ]
    required_docs_snippets = [
        "`repo_owned` is a trust and registration boundary",
        "workflow-facing labels still stay org capability classes",
        "It must not resolve to a known repo-label fossil.",
        "forks because publish jobs are still gated by tag/workflow policy",
    ]
    forbidden_docs_snippets = [
        "- validate and publish on repo-specific runner labels",
        "repo-owned dedicated lane",
    ]

    ok = True
    for snippet in required_workflow_snippets:
        if snippet not in workflow:
            print(
                f"{workflow_path.relative_to(ROOT)}: missing runner contract snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False
    for snippet in required_docs_snippets:
        if snippet not in docs:
            print(
                f"{docs_path.relative_to(ROOT)}: missing runner contract snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False
    for snippet in forbidden_docs_snippets:
        if snippet in docs:
            print(
                f"{docs_path.relative_to(ROOT)}: stale runner contract snippet remains: {snippet}",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print("js-bazel-package runner contract documented and guarded")
    return 0


def check_flywheel_reapi_proof_contract() -> int:
    action_path = ROOT / ".github/actions/flywheel-reapi-proof/action.yml"
    readme_path = ROOT / "README.md"
    roadmap_path = ROOT / "docs/roadmap.md"
    action = action_path.read_text(encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    roadmap = roadmap_path.read_text(encoding="utf-8")

    required_action_snippets = [
        "request_id:",
        "-f request_id=\"${request_id}\"",
        "--json databaseId,createdAt,displayTitle",
        "contains($request_id)",
        "request_id=${request_id}",
    ]
    forbidden_action_snippets = [
        "sort_by(.createdAt, .databaseId) | last",
    ]
    required_readme_snippet = "correlated by a unique request id"
    required_roadmap_snippets = [
        "timestamp-only child-run resolution",
        "concurrent consumer proofs",
    ]

    ok = True
    for snippet in required_action_snippets:
        if snippet not in action:
            print(
                f"{action_path.relative_to(ROOT)}: missing request-id correlation snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False
    for snippet in forbidden_action_snippets:
        if snippet in action:
            print(
                f"{action_path.relative_to(ROOT)}: stale timestamp-only correlation remains: {snippet}",
                file=sys.stderr,
            )
            ok = False
    if required_readme_snippet not in readme:
        print(
            f"{readme_path.relative_to(ROOT)}: missing request-id correlation docs",
            file=sys.stderr,
        )
        ok = False
    for snippet in required_roadmap_snippets:
        if snippet not in roadmap:
            print(
                f"{roadmap_path.relative_to(ROOT)}: missing timestamp-only correlation warning: {snippet}",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print("flywheel-reapi-proof request-id correlation guarded")
    return 0


def check_immutable_release_contract() -> int:
    action_path = ROOT / ".github/actions/immutable-release-verify/action.yml"
    verifier_path = ROOT / "scripts/immutable-release-verify.sh"
    selftest_path = ROOT / "scripts/immutable-release-verify-selftest.sh"
    workflow_path = ROOT / ".github/workflows/js-bazel-package.yml"
    release_path = ROOT / ".github/workflows/release.yml"
    docs_path = ROOT / "docs/js-bazel-package.md"
    releasing_path = ROOT / "RELEASING.md"
    workflow_selftest_path = ROOT / "scripts/immutable-release-workflow-selftest.sh"

    paths = [
        action_path,
        verifier_path,
        selftest_path,
        workflow_path,
        release_path,
        docs_path,
        releasing_path,
        workflow_selftest_path,
    ]
    ok = True
    for path in paths:
        if not path.exists():
            print(f"missing {path.relative_to(ROOT)}", file=sys.stderr)
            ok = False
    if not ok:
        return 1

    action = action_path.read_text(encoding="utf-8")
    verifier = verifier_path.read_text(encoding="utf-8")
    selftest = selftest_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")
    release = release_path.read_text(encoding="utf-8")
    docs = docs_path.read_text(encoding="utf-8")
    releasing = releasing_path.read_text(encoding="utf-8")
    workflow_selftest = workflow_selftest_path.read_text(encoding="utf-8")

    required_action_snippets = [
        "mode:",
        "expected-source-sha:",
        "admin-token:",
        "contents-token:",
        "verify-attempts:",
        "IMMUTABLE_RELEASE_ADMIN_TOKEN",
        "IMMUTABLE_RELEASE_CONTENTS_TOKEN",
        "scripts/immutable-release-verify.sh",
    ]
    required_verifier_snippets = [
        'readonly API_VERSION="2026-03-10"',
        "repos/${repository}/immutable-releases",
        "mode must be settings or published",
        "settings mode does not accept a Contents token",
        "published mode does not accept an Administration token",
        "unset IMMUTABLE_RELEASE_ADMIN_TOKEN IMMUTABLE_RELEASE_CONTENTS_TOKEN GH_TOKEN",
        "unset admin_token",
        "git/ref/tags/${encoded_tag}",
        "git/tags/${object_sha}",
        'ref_object_sha="$object_sha"',
        '.enabled == true',
        '.immutable == true',
        "gh release verify",
        "https://in-toto.io/attestation/release/v0.2",
        "$predicate.repository",
        "$predicate.tag",
        ".digest[$digest_algorithm]",
        "direct tag ref object $ref_object_sha",
        "published release did not become immutable and attestable",
    ]
    required_workflow_snippets = [
        "require_immutable_release:",
        "IMMUTABLE_RELEASE_APP_CLIENT_ID:",
        "IMMUTABLE_RELEASE_APP_PRIVATE_KEY:",
        "attestations: read",
        "Require release:published for immutable publication",
        "github.event_name == 'release' && github.event.action == 'published'",
        "permission-administration: read",
        "Mint Administration-read installation token",
        "Verify immutable-release setting",
        "Verify immutable published release",
        "inputs.require_immutable_release &&",
        "mode: settings",
        "mode: published",
        "expected-source-sha: ${{ github.sha }}",
    ]
    required_release_snippets = [
        "immutable-release-settings:",
        "permissions: {}",
        "Verify immutable-release setting before mutation",
        "Cut or reuse exact version tag",
        "Create or reuse immutable GitHub Release",
        "Verify published attestation and source binding",
        "Move floating major after published verification",
        "queue: max",
        "--verify-tag",
        "Reusing exact $VERSION tag from an interrupted release attempt",
        "retry is complete",
        "refusing rollback to $VERSION",
    ]
    required_docs_snippets = [
        "`require_immutable_release`",
        "Administration read",
        "release:published",
        "`target_commitish`",
        "`gh release verify`",
        "attestations: read",
        "runtime",
    ]
    required_releasing_snippets = [
        "Attestations read",
        "queue: max",
        "refuses to move the floating major backward",
    ]

    for path, text, snippets in (
        (action_path, action, required_action_snippets),
        (verifier_path, verifier, required_verifier_snippets),
        (workflow_path, workflow, required_workflow_snippets),
        (release_path, release, required_release_snippets),
        (docs_path, docs, required_docs_snippets),
        (releasing_path, releasing, required_releasing_snippets),
    ):
        for snippet in snippets:
            if snippet not in text:
                print(
                    f"{path.relative_to(ROOT)}: missing immutable-release snippet: {snippet}",
                    file=sys.stderr,
                )
                ok = False

    input_block = re.search(
        r"\n      require_immutable_release:\n(?:.*\n)*?        default: (\w+)\n",
        workflow,
    )
    if not input_block or input_block.group(1) != "false":
        print(
            f"{workflow_path.relative_to(ROOT)}: require_immutable_release must "
            "declare default: false",
            file=sys.stderr,
        )
        ok = False

    for secret_name in (
        "IMMUTABLE_RELEASE_APP_CLIENT_ID",
        "IMMUTABLE_RELEASE_APP_PRIVATE_KEY",
    ):
        secret_block = re.search(
            rf"\n      {secret_name}:\n(?:.*\n)*?        required: (\w+)\n",
            workflow,
        )
        if not secret_block or secret_block.group(1) != "false":
            print(
                f"{workflow_path.relative_to(ROOT)}: {secret_name} must stay "
                "optional for default-off callers",
                file=sys.stderr,
            )
            ok = False

    if "target_commitish" in verifier:
        print(
            f"{verifier_path.relative_to(ROOT)}: must not trust release.target_commitish",
            file=sys.stderr,
        )
        ok = False
    if verifier.count('api_get "$admin_token"') != 1:
        print(
            f"{verifier_path.relative_to(ROOT)}: Administration token must be isolated "
            "to exactly one setting request",
            file=sys.stderr,
        )
        ok = False

    if "IMMUTABLE_RELEASE_ADMIN_TOKEN" in workflow or "IMMUTABLE_RELEASE_ADMIN_TOKEN" in release:
        print(
            "workflows must mint an installation token at runtime, not consume a stored token",
            file=sys.stderr,
        )
        ok = False

    self_ref_pattern = re.compile(
        r"tinyland-inc/ci-templates/\.github/actions/immutable-release-verify@([^\s]+)"
    )
    self_refs = self_ref_pattern.findall(workflow + "\n" + release)
    if len(self_refs) != 4 or any(not re.fullmatch(r"[0-9a-f]{40}", ref) for ref in self_refs):
        print(
            "all four privileged self-action calls must use immutable full commit SHAs",
            file=sys.stderr,
        )
        ok = False
    elif len(set(self_refs)) != 1:
        print("privileged self-action calls must pin one reviewed implementation", file=sys.stderr)
        ok = False

    app_ref_pattern = re.compile(r"actions/create-github-app-token@([^\s]+)")
    app_refs = app_ref_pattern.findall(workflow + "\n" + release)
    if len(app_refs) != 2 or any(not re.fullmatch(r"[0-9a-f]{40}", ref) for ref in app_refs):
        print("runtime App-token mint actions must use immutable full commit SHAs", file=sys.stderr)
        ok = False

    resolve_block = workflow[workflow.find("  resolve-runner:") : workflow.find("  validate:")]
    if (
        "attestations: read" not in resolve_block
        or "contents: read" not in resolve_block
        or "packages: write" in resolve_block
    ):
        print(
            f"{workflow_path.relative_to(ROOT)}: verifier job must have Attestations/Contents read only and no package-write authority",
            file=sys.stderr,
        )
        ok = False

    settings_start = release.find("  immutable-release-settings:")
    publish_start = release.find("  publish-version-release:")
    verify_start = release.find("  verify-published-release:")
    floating_start = release.find("  move-floating-major:")
    settings_block = release[settings_start:publish_start]
    publish_block = release[publish_start:verify_start]
    verify_block = release[verify_start:floating_start]
    if "permissions: {}" not in settings_block or "contents: write" in settings_block:
        print("Administration verifier job must have no GITHUB_TOKEN write authority", file=sys.stderr)
        ok = False
    if "immutable-release-settings" not in publish_block or "contents: write" not in publish_block:
        print("version-tag/Release mutation must depend on settings precheck", file=sys.stderr)
        ok = False
    if (
        "publish-version-release" not in verify_block
        or "attestations: read" not in verify_block
        or "contents: read" not in verify_block
    ):
        print(
            "published verifier must follow mutation with Attestations/Contents read only",
            file=sys.stderr,
        )
        ok = False
    floating_block = release[floating_start:]
    if "verify-published-release" not in floating_block or "contents: write" not in floating_block:
        print("floating-major mutation must depend on published verification", file=sys.stderr)
        ok = False
    if "refusing rollback to $VERSION" not in floating_block:
        print("floating-major mutation must reject cross-version rollback", file=sys.stderr)
        ok = False

    checkout_refs = re.findall(r"actions/checkout@([^\s]+)", release)
    expected_checkout_ref = "de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    if len(checkout_refs) != 4 or any(ref != expected_checkout_ref for ref in checkout_refs):
        print(
            f"{release_path.relative_to(ROOT)}: all release checkouts must pin "
            f"the reviewed {expected_checkout_ref} commit",
            file=sys.stderr,
        )
        ok = False

    if "queue: max" not in release or "cancel-in-progress: true" in release:
        print(
            f"{release_path.relative_to(ROOT)}: release concurrency must retain pending runs without cancelling active transactions",
            file=sys.stderr,
        )
        ok = False

    settings_index = release.find("- name: Verify immutable-release setting before mutation")
    tag_index = release.find("- name: Cut or reuse exact version tag")
    publish_index = release.find("- name: Create or reuse immutable GitHub Release")
    verify_index = release.find("- name: Verify published attestation and source binding")
    floating_index = release.find("- name: Move floating major after published verification")
    if not (
        -1 < settings_index < tag_index < publish_index < verify_index < floating_index
    ):
        print(
            f"{release_path.relative_to(ROOT)}: release authority must advance "
            "settings -> version tag -> Release -> published verify -> floating major",
            file=sys.stderr,
        )
        ok = False

    required_workflow_test_snippets = [
        "tag push is rejected",
        "manual branch publication is rejected",
        "retry reuses exact version tag",
        "conflicting existing version tag fails closed",
        "retry reuses published Release",
        "conflicting version tag cannot move floating major",
        "older release rerun cannot roll floating major backward",
        "durable queue",
    ]
    for snippet in required_workflow_test_snippets:
        if snippet not in workflow_selftest:
            print(
                f"{workflow_selftest_path.relative_to(ROOT)}: missing event/transaction test: {snippet}",
                file=sys.stderr,
            )
            ok = False

    required_verifier_test_snippets = [
        "annotated tag binds direct ref object and peels to expected commit",
        "attestation-peeled-digest",
        "direct tag ref object aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]
    for snippet in required_verifier_test_snippets:
        if snippet not in selftest:
            print(
                f"{selftest_path.relative_to(ROOT)}: missing direct-ref attestation test: {snippet}",
                file=sys.stderr,
            )
            ok = False

    for prose_path, prose in ((docs_path, docs),):
        if "IMMUTABLE_RELEASE_ADMIN_TOKEN" in prose:
            print(
                f"{prose_path.relative_to(ROOT)}: stale stored installation-token guidance remains",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print("immutable-release verifier is default-off, token-isolated, and release-ordered")
    return 0


def check_cache_backed_optin_contract() -> int:
    """Guard the TIN-2110 opt-in cache-backed lane: default-off and cache-first.

    Asserts the new `cache_backed` input is default-off, the default Bazel
    validation step stays guarded so non-opted consumers are byte-identical, the
    cache-backed step routes through `--config=ci-cached` + injected
    `--remote_cache`, gates on the cache-attachment contract, and NEVER wires a
    remote executor (cache-first only, TIN-1997 Option D).
    """
    workflow_path = ROOT / ".github/workflows/js-bazel-package.yml"
    docs_path = ROOT / "docs/js-bazel-package.md"
    bazelrc_path = ROOT / "bazelrc/ci-cached.bazelrc"
    flywheel_bazelrc_path = ROOT / "bazelrc/flywheel.bazelrc"
    contract_path = ROOT / "scripts/cache-attachment-contract.sh"
    workflow = workflow_path.read_text(encoding="utf-8")
    docs = docs_path.read_text(encoding="utf-8")

    ok = True

    if not contract_path.exists():
        print(f"missing {contract_path.relative_to(ROOT)}", file=sys.stderr)
        ok = False
    if not bazelrc_path.exists():
        print(f"missing {bazelrc_path.relative_to(ROOT)}", file=sys.stderr)
        ok = False
    if not flywheel_bazelrc_path.exists():
        print(f"missing {flywheel_bazelrc_path.relative_to(ROOT)}", file=sys.stderr)
        ok = False

    # Input is declared and default-off.
    if not re.search(r"\n      cache_backed:\n", workflow):
        print(f"{workflow_path.relative_to(ROOT)}: missing cache_backed input", file=sys.stderr)
        ok = False
    cache_backed_block = re.search(
        r"\n      cache_backed:\n(?:.*\n)*?        default: (\w+)\n", workflow
    )
    if not cache_backed_block or cache_backed_block.group(1) != "false":
        print(
            f"{workflow_path.relative_to(ROOT)}: cache_backed must declare default: false",
            file=sys.stderr,
        )
        ok = False

    required_workflow_snippets = [
        # default path stays guarded => byte-identical for non-opted consumers
        "if: ${{ !inputs.cache_backed }}",
        # opt-in path gated on the fail-closed cache-attachment contract
        "Assert shared-cache attachment (cache-backed lane)",
        "cache-attachment-contract.sh",
        "--strict",
        # opt-in path is cache-first: ci-cached config + injected remote cache, no upload
        "--config=ci-cached",
        "--remote_cache=${BAZEL_REMOTE_CACHE}",
        "--remote_upload_local_results=false",
        # the unchanged default command must still be present verbatim
        'run_with_bazel_fetch_retry "Validate Bazel targets" '
        '"npx --yes @bazel/bazelisk build ${targets_quoted}--verbose_failures"',
        # TIN-2109: manifest validation in the cache-backed lane (fail-closed)
        "Validate repo manifest (cache-backed lane)",
        "repo-manifest-validate@v2",
        # TIN-2109: expected mode is manifest-driven (enrollment.substrateMode)
        ".enrollment.substrateMode",
        "GF_BAZEL_SUBSTRATE_MODE=",
        "GF_FLYWHEEL_PROFILE_STATE=",
        # TIN-2109: runner labels fed so the contract rejects hosted/repo-label fallback
        "GF_BAZEL_RUNNER_LABELS=",
        "join(runner.labels, ',')",
        # TIN-2109: fetch fallback pinned to the immutable releasing tag, not floating v2
        "CI_TEMPLATES_REF: v2.5.1",
    ]
    for snippet in required_workflow_snippets:
        if snippet not in workflow:
            print(
                f"{workflow_path.relative_to(ROOT)}: missing cache-backed snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    # TIN-2109: the floating-major fallback ref must NOT appear (it is pinned).
    if re.search(r"CI_TEMPLATES_REF:\s*v2\s*$", workflow, re.MULTILINE):
        print(
            f"{workflow_path.relative_to(ROOT)}: cache-backed fetch fallback uses floating "
            "CI_TEMPLATES_REF: v2; pin to the immutable releasing tag",
            file=sys.stderr,
        )
        ok = False

    # TIN-2109: the manifest validator must be dependency-free (no nix/network)
    # so the gate works on nix self-hosted cluster runners.
    validator_path = ROOT / "scripts/manifest-schema-validate.py"
    action_path = ROOT / ".github/actions/repo-manifest-validate/action.yml"
    if not validator_path.exists():
        print(f"missing {validator_path.relative_to(ROOT)}", file=sys.stderr)
        ok = False
    if action_path.exists():
        action_text = action_path.read_text(encoding="utf-8")
        if "manifest-schema-validate.py" not in action_text:
            print(
                f"{action_path.relative_to(ROOT)}: repo-manifest-validate must use the "
                "bundled stdlib validator (manifest-schema-validate.py)",
                file=sys.stderr,
            )
            ok = False
        if "nix develop --command python3" in action_text:
            print(
                f"{action_path.relative_to(ROOT)}: repo-manifest-validate must not depend on "
                "`nix develop` (fails on nix-store lock on cluster runners)",
                file=sys.stderr,
            )
            ok = False

    # TIN-2109: the contract script must DEFINE+ENFORCE the hardened gate behaviors.
    contract = contract_path.read_text(encoding="utf-8") if contract_path.exists() else ""
    required_contract_snippets = [
        # hosted / non-cluster runner rejection (no silent degrade)
        "GF_BAZEL_RUNNER_LABELS",
        "GF_BAZEL_ALLOW_HOSTED_RUNNER",
        "classify_runner",
        # executor-backed contract: full required set, defined + enforced
        "GF_FLYWHEEL_PROFILE_STATE",
        "GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST",
        'executor-backed mode requires BAZEL_REMOTE_CACHE',
    ]
    for snippet in required_contract_snippets:
        if snippet not in contract:
            print(
                f"{contract_path.relative_to(ROOT)}: missing TIN-2109 contract snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    # CACHE-FIRST: the workflow must never wire a remote executor anywhere.
    for forbidden in ("--remote_executor", "--config=executor-backed", "BAZEL_REMOTE_EXECUTOR"):
        if forbidden in workflow:
            print(
                f"{workflow_path.relative_to(ROOT)}: cache-first lane must not wire executor: {forbidden}",
                file=sys.stderr,
            )
            ok = False

    if "cache-backed" not in docs.lower() and "cache_backed" not in docs:
        print(
            f"{docs_path.relative_to(ROOT)}: missing cache-backed lane documentation",
            file=sys.stderr,
        )
        ok = False

    # Fresh consumers must be able to attach without declaring a
    # @gloriousflywheel Bzlmod repo. The wrapper/action passes platform identity
    # as a remote default exec property.
    flywheel_bazelrc = (
        flywheel_bazelrc_path.read_text(encoding="utf-8")
        if flywheel_bazelrc_path.exists()
        else ""
    )
    if "@gloriousflywheel//platforms" in flywheel_bazelrc:
        print(
            f"{flywheel_bazelrc_path.relative_to(ROOT)}: fresh spokes must not require "
            "@gloriousflywheel//platforms; use gf.platform remote exec properties",
            file=sys.stderr,
        )
        ok = False
    for required in (
        "common:flywheel-executor --remote_local_fallback=false",
        "common:flywheel-executor --spawn_strategy=remote",
    ):
        if required not in flywheel_bazelrc:
            print(
                f"{flywheel_bazelrc_path.relative_to(ROOT)}: missing executor-backed "
                f"force-remote setting: {required}",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print("cache-backed opt-in lane is default-off and cache-first")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "check",
        choices=[
            "manifest",
            "internal-refs",
            "js-bazel-runner-contract",
            "immutable-release-contract",
            "flywheel-reapi-proof-contract",
            "cache-backed-optin-contract",
        ],
    )
    args = parser.parse_args()

    if args.check == "manifest":
        return validate_manifest()
    if args.check == "js-bazel-runner-contract":
        return check_js_bazel_package_runner_contract()
    if args.check == "immutable-release-contract":
        return check_immutable_release_contract()
    if args.check == "flywheel-reapi-proof-contract":
        return check_flywheel_reapi_proof_contract()
    if args.check == "cache-backed-optin-contract":
        return check_cache_backed_optin_contract()
    return check_internal_refs()


if __name__ == "__main__":
    raise SystemExit(main())
