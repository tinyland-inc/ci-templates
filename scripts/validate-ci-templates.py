#!/usr/bin/env python3
"""Repository-local validation helpers for tinyland-inc/ci-templates."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shlex
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUST_BAZEL_RELEASE = "v2.14.0"
RUST_BAZEL_CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
RUBY_USES_SCRIPT = r"""
require "json"
require "yaml"

document = YAML.safe_load(
  STDIN.read,
  permitted_classes: [],
  permitted_symbols: [],
  aliases: true,
)
references = []
walk = nil
walk = lambda do |node|
  case node
  when Hash
    node.each do |key, value|
      if key.to_s == "uses"
        references << value
      else
        walk.call(value)
      end
    end
  when Array
    node.each { |value| walk.call(value) }
  end
end
walk.call(document)
puts JSON.generate(references)
"""


def structural_uses(document: str) -> list[str]:
    """Return every YAML `uses` value without relying on textual spelling."""

    result = subprocess.run(
        ["ruby", "-e", RUBY_USES_SCRIPT],
        input=document,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "Ruby YAML parser failed")
    try:
        references = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ruby YAML parser emitted invalid JSON: {exc}") from exc
    if not isinstance(references, list) or any(
        not isinstance(reference, str) or not reference for reference in references
    ):
        raise ValueError("every YAML uses value must be a non-empty string")
    return references


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


# The floating major this repo currently ships. A workflow's or composite's
# internal action refs must track it, or that file is frozen: `uses:` resolves
# the action at ITS OWN ref, so a ref left on the previous major keeps serving
# that major's actions forever, no matter what lands on main.
#
# This is not hypothetical. Every `@v2` ref froze at v2.14.0 when v3.0.0 was
# cut, which meant `secrets-scan` kept installing gitleaks 8.21.2 — the version
# that silently ignores a repo's `[[allowlists]]` table, the exact bug TIN-3900
# fixed and v3.0.0 shipped. The fix reached nobody. The check below used to
# discard the ref entirely (`for action, _ref in …`), so nothing said so.
CURRENT_RELEASE_LINE = "v3"

# Files still on the previous line, with the ticket that unfreezes them. This is
# a debt ledger, not a permanent exemption: an entry means "known stale", and a
# file NOT listed here that carries a stale ref fails. An entry that no longer
# has a stale ref also fails, so the ledger cannot rot into a lie. Deleting
# entries is the follow-up's job. Their v2->v3 action delta is currently
# description-only (`nix-setup`), which is why they are sequenced separately
# from spoke-ci, where the delta is the gitleaks fix above.
STALE_INTERNAL_REF_FILES = {
    ".github/workflows/js-bazel-package.yml": "TIN-3914",
    ".github/workflows/spoke-deploy-cloudflare-pages.yml": "TIN-3914",
    ".github/workflows/spoke-public-preview.yml": "TIN-3914",
}


def check_internal_refs() -> int:
    ok = True
    action_pattern = re.compile(
        r"tinyland-inc/ci-templates/\.github/actions/([^@\s]+)@([^\s#]+)"
    )
    main_pattern = re.compile(r"tinyland-inc/ci-templates/.*@main")
    exact_release = re.compile(r"\Av\d+\.\d+\.\d+\Z")

    for path in sorted((ROOT / ".github").glob("**/*.yml")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for action, ref in action_pattern.findall(text):
            action_yml = ROOT / ".github/actions" / action / "action.yml"
            if not action_yml.exists():
                print(f"{rel}: missing internal action {action_yml.relative_to(ROOT)}", file=sys.stderr)
                ok = False
            # An exact SemVer ref is the restricted workflows' immutability
            # contract (restricted-workflow-contract.rb pins the exact release
            # and rejects anything floating), so it is always admissible here.
            if exact_release.match(ref) or ref == CURRENT_RELEASE_LINE:
                continue
            if str(rel) in STALE_INTERNAL_REF_FILES:
                continue
            print(
                f"{rel}: internal action {action}@{ref} is not on the current release line "
                f"@{CURRENT_RELEASE_LINE} and is not an exact release pin; a stale floating "
                "major freezes this file's actions at the previous major",
                file=sys.stderr,
            )
            ok = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            if main_pattern.search(line):
                print(f"{rel}:{line_no}: internal ci-templates ref uses @main", file=sys.stderr)
                ok = False

    for rel_path, ticket in sorted(STALE_INTERNAL_REF_FILES.items()):
        target = ROOT / rel_path
        if not target.exists():
            print(f"{rel_path}: listed as stale but does not exist; prune the ledger", file=sys.stderr)
            ok = False
            continue
        stale = [
            f"{action}@{ref}"
            for action, ref in action_pattern.findall(target.read_text(encoding="utf-8"))
            if not exact_release.match(ref) and ref != CURRENT_RELEASE_LINE
        ]
        if not stale:
            print(
                f"{rel_path}: no longer has stale internal refs; remove it from "
                f"STALE_INTERNAL_REF_FILES ({ticket})",
                file=sys.stderr,
            )
            ok = False
        else:
            print(f"::notice::{rel_path}: {len(stale)} internal ref(s) still on the previous release line ({ticket})")

    if not ok:
        return 1
    print(f"internal action refs resolve and track @{CURRENT_RELEASE_LINE} (or an exact release pin)")
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
        "forks because this workflow has no registry publication job or publish credential",
        "BCR is the only package publication authority",
    ]
    forbidden_workflow_snippets = [
        "publish-npm:",
        "publish-github:",
        "npm publish",
        "npm.pkg.github.com",
        "registry.npmjs.org",
        "NPM_TOKEN",
        "TINYLAND_GITHUB_PACKAGES_TOKEN",
        "npx --yes @bazel/bazelisk",
        "pnpm/action-setup",
        "actions/setup-node",
        "pnpm install",
        "node_versions",
        "workspace_mode",
        "metadata_check_command",
        "prepare_command",
        "lint_command",
        "typecheck_command",
        "unit_test_command",
        "integration_test_command",
        "build_command",
        "package_check_command",
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

    for snippet in forbidden_workflow_snippets:
        if snippet in workflow:
            print(
                f"{workflow_path.relative_to(ROOT)}: deprecated package publication or npx fallback remains: {snippet}",
                file=sys.stderr,
            )
            ok = False

    retired_workflow = ROOT / ".github/workflows/npm-publish.yml"
    if retired_workflow.exists():
        print(
            f"{retired_workflow.relative_to(ROOT)}: standalone npm publication workflow must stay removed",
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
    print("js-bazel-package runner and Bzlmod/BCR authority contract documented and guarded")
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


#: The step of `.github/actions/repo-manifest-validate/action.yml` that runs the
#: bundled manifest validator. Guards below read THIS step's shell, not the file.
MANIFEST_VALIDATE_STEP = "Validate repo manifest schema"
MANIFEST_VALIDATOR_BASENAME = "manifest-schema-validate.py"

_SHELL_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_SHELL_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_shell_vars(text: str, env: dict[str, str]) -> str:
    """Substitute `$name`/`${name}` from `env` until it stops changing.

    Enough to follow `validator="$action_dir/../../scripts/foo.py"` to a path
    the guard can recognise. Unknown names are left verbatim (`${{ github.* }}`
    is deliberately not an identifier, so it survives untouched).
    """
    for _ in range(8):
        expanded = _SHELL_VAR.sub(
            lambda m: env.get(m.group(1) or m.group(2), m.group(0)), text
        )
        if expanded == text:
            return text
        text = expanded
    return text


def _composite_step_run_body(action_text: str, step_name: str) -> str | None:
    """Return the `run:` shell of the named composite step, or None if absent."""
    lines = action_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^(\s*)- name:\s*{re.escape(step_name)}\s*$", line):
            start = index
            indent = len(line) - len(line.lstrip())
            break
    if start is None:
        return None

    body: list[str] = []
    run_indent = None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("- name:") and (len(line) - len(line.lstrip())) <= indent:
            break  # next step at the same list level
        if run_indent is None:
            if re.match(r"^\s*run:\s*[|>]", line):
                run_indent = len(line) - len(line.lstrip())
            continue
        if stripped and (len(line) - len(line.lstrip())) <= run_indent:
            break  # dedented back out of the block scalar
        body.append(line)
    return None if run_indent is None else "\n".join(body)


def manifest_validator_invocations(
    action_text: str,
) -> tuple[list[list[str]] | None, list[str]]:
    """Every argv in the manifest-validation step that RUNS the bundled validator.

    Why parse instead of `"--schemas-dir" in action_text`: a whole-file
    substring test is satisfied by any occurrence anywhere, including the
    comment in this very step that explains why `--schemas-dir` is passed. A
    guard its own documentation satisfies proves nothing about the code — delete
    the flag from the command, keep the paragraph above it, and the substring
    test still passes while every consumer is silently re-pinned to v1. So:
    take the step's `run:` block, drop comments (`shlex(comments=True)` knows a
    `#` inside quotes is not one), resolve shell variables, and look at the
    argument vectors that actually execute.

    Returns `(invocations, unlexable_lines)`; `invocations` is None when the
    step itself is missing. A line the lexer cannot read is reported rather than
    skipped: a guard that quietly ignores what it cannot parse is the same
    failure in a new place.
    """
    body = _composite_step_run_body(action_text, MANIFEST_VALIDATE_STEP)
    if body is None:
        return None, []

    env: dict[str, str] = {}
    invocations: list[list[str]] = []
    unlexable: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            unlexable.append(line)
            continue
        if not tokens:
            continue
        assignment = _SHELL_ASSIGN.match(tokens[0]) if len(tokens) == 1 else None
        if assignment:
            env[assignment.group(1)] = _expand_shell_vars(assignment.group(2), env)
            continue
        argv = [_expand_shell_vars(token, env) for token in tokens]
        interpreter = pathlib.PurePosixPath(argv[0]).name
        runs_validator = argv[0].endswith(MANIFEST_VALIDATOR_BASENAME) or (
            interpreter in {"python", "python3"}
            and any(a.endswith(MANIFEST_VALIDATOR_BASENAME) for a in argv[1:])
        )
        if runs_validator:
            invocations.append(argv)
    return invocations, unlexable


def check_cache_backed_optin_contract() -> int:
    """Guard the TIN-2110 cache-backed lane: default-off and cache-first.

    The default lane uses the GF/Nix Bazelisk front door. The cache-backed lane
    adds `--config=ci-cached` plus the injected `--remote_cache`, gates on the
    cache-attachment contract, and never wires a remote executor.
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
        # the default GF/Nix Bazelisk path stays separate from the cache-backed path
        "if: ${{ !inputs.cache_backed }}",
        # opt-in path gated on the fail-closed cache-attachment contract
        "Assert shared-cache attachment (cache-backed lane)",
        "cache-attachment-contract.sh",
        "--strict",
        # opt-in path is cache-first: ci-cached config + injected remote cache, no upload
        "--config=ci-cached",
        "--remote_cache=${BAZEL_REMOTE_CACHE}",
        "--remote_upload_local_results=false",
        # the default graph-proof command must be present verbatim
        'run_with_bazel_fetch_retry "Validate Bazel targets" '
        '"bazelisk build ${targets_quoted}--verbose_failures"',
        "command -v bazelisk",
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
        if "nix develop --command python3" in action_text:
            print(
                f"{action_path.relative_to(ROOT)}: repo-manifest-validate must not depend on "
                "`nix develop` (fails on nix-store lock on cluster runners)",
                file=sys.stderr,
            )
            ok = False

        # Everything below reads the ARGUMENT VECTORS of the validation step,
        # never the file text. The action must hand the validator the schema
        # DIRECTORY and let it route by schema_version: naming one schema file
        # pins every consumer to that version, which is the shipped defect —
        # `schemas/tinyland-repo-manifest.schema.json` hardcoded, so a repo on
        # the published schema_version 2 failed with `at /schema_version: 1 was
        # expected`, the gate blaming the manifest for a branch it lacked.
        invocations, unlexable = manifest_validator_invocations(action_text)
        rel_action = action_path.relative_to(ROOT)
        if invocations is None:
            print(
                f"{rel_action}: no `{MANIFEST_VALIDATE_STEP}` step with a run: block; the "
                "manifest gate's guards have nothing to read",
                file=sys.stderr,
            )
            ok = False
        elif unlexable:
            print(
                f"{rel_action}: cannot lex {len(unlexable)} line(s) of the "
                f"`{MANIFEST_VALIDATE_STEP}` step ({unlexable[0]!r}); refusing to report a "
                "verdict on shell this guard cannot read",
                file=sys.stderr,
            )
            ok = False
        elif not invocations:
            print(
                f"{rel_action}: the `{MANIFEST_VALIDATE_STEP}` step never executes "
                f"scripts/{MANIFEST_VALIDATOR_BASENAME}; a comment naming it is not a gate",
                file=sys.stderr,
            )
            ok = False
        else:
            for argv in invocations:
                if "--schemas-dir" not in argv:
                    print(
                        f"{rel_action}: `{MANIFEST_VALIDATE_STEP}` runs the validator as "
                        f"{shlex.join(argv)} — it must pass --schemas-dir and let "
                        f"scripts/{MANIFEST_VALIDATOR_BASENAME} route by schema_version; "
                        "naming a single schema file hardcodes one manifest version",
                        file=sys.stderr,
                    )
                    ok = False
                named = [
                    a
                    for a in argv
                    if re.search(r"tinyland-repo-manifest[^/\s]*\.schema\.json", a)
                ]
                if named:
                    print(
                        f"{rel_action}: `{MANIFEST_VALIDATE_STEP}` passes {named[0]} to the "
                        "validator, resolving a specific manifest schema itself; the "
                        "version -> schema mapping belongs in SCHEMA_BY_VERSION "
                        f"(scripts/{MANIFEST_VALIDATOR_BASENAME}) only",
                        file=sys.stderr,
                    )
                    ok = False

        # Every version the validator claims to support must actually be
        # vendored here. A mapping entry with no file on disk is a version that
        # is nominally supported and factually ungated.
        validator_text = validator_path.read_text(encoding="utf-8")
        mapped = re.findall(r"^\s*(\d+):\s*\"([^\"]+\.schema\.json)\",", validator_text, re.M)
        if not mapped:
            print(
                f"{validator_path.relative_to(ROOT)}: SCHEMA_BY_VERSION parsed as empty; the "
                "routing table is the whole gate and must not be silently unreadable",
                file=sys.stderr,
            )
            ok = False
        for version, schema_name in mapped:
            if not (ROOT / "schemas" / schema_name).is_file():
                print(
                    f"{validator_path.relative_to(ROOT)}: schema_version {version} maps to "
                    f"schemas/{schema_name}, which is not vendored in this repo",
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


def check_rust_bazel_application_contract() -> int:
    """Guard the opt-in native Rust+Bazel application workflow."""
    workflow_path = ROOT / ".github/workflows/rust-bazel-application.yml"
    action_path = ROOT / ".github/actions/rust-bazel-contract/action.yml"
    preflight_action_path = ROOT / ".github/actions/rust-bazel-preflight/action.yml"
    custody_action_path = (
        ROOT / ".github/actions/rust-bazel-binary-custody/action.yml"
    )
    custody_contract_path = (
        ROOT / ".github/actions/rust-bazel-binary-custody/custody.py"
    )
    contract_path = ROOT / ".github/actions/rust-bazel-contract/contract.py"
    driver_path = ROOT / ".github/actions/rust-bazel-contract/bazelisk-ci"
    docs_path = ROOT / "docs/rust-bazel-application.md"
    paths = (
        workflow_path,
        action_path,
        preflight_action_path,
        custody_action_path,
        custody_contract_path,
        contract_path,
        driver_path,
        docs_path,
    )
    ok = True
    for path in paths:
        if not path.is_file():
            print(f"missing {path.relative_to(ROOT)}", file=sys.stderr)
            ok = False
    if not ok:
        return 1

    workflow = workflow_path.read_text(encoding="utf-8")
    action = action_path.read_text(encoding="utf-8")
    preflight_action = preflight_action_path.read_text(encoding="utf-8")
    custody_action = custody_action_path.read_text(encoding="utf-8")
    custody_contract = custody_contract_path.read_text(encoding="utf-8")
    contract = contract_path.read_text(encoding="utf-8")
    driver = driver_path.read_text(encoding="utf-8")
    docs = docs_path.read_text(encoding="utf-8")

    uses_oracles = {
        "      uses: actions/checkout@abc": ["actions/checkout@abc"],
        "      - uses: evil/action@main": ["evil/action@main"],
        "      - uses: './local-action'": ["./local-action"],
        "      - {uses: inline/action@main}": ["inline/action@main"],
        '      "uses": quoted/action@main': ["quoted/action@main"],
        "      - uses : spaced/action@main": ["spaced/action@main"],
    }
    for fragment, expected in uses_oracles.items():
        sample = f"steps:\n{fragment}\n"
        try:
            observed = structural_uses(sample)
        except ValueError as exc:
            print(
                f"Rust+Bazel structural uses parser rejected oracle {fragment!r}: {exc}",
                file=sys.stderr,
            )
            ok = False
            continue
        if observed != expected:
            print(
                "Rust+Bazel structural uses parser returned the wrong closure for "
                f"{fragment!r}: expected {expected}, got {observed}",
                file=sys.stderr,
            )
            ok = False

    closure_errors: list[str] = []
    closure_queue = [workflow_path]
    closure_visited: set[pathlib.Path] = set()
    internal_actions: set[str] = set()
    external_actions: set[str] = set()
    while closure_queue:
        closure_path = closure_queue.pop()
        if closure_path in closure_visited:
            continue
        closure_visited.add(closure_path)
        closure_text = closure_path.read_text(encoding="utf-8")
        try:
            references = structural_uses(closure_text)
        except ValueError as exc:
            closure_errors.append(
                f"{closure_path.relative_to(ROOT)}: cannot parse immutable action closure: {exc}"
            )
            continue
        for reference in references:
            if reference.startswith("./"):
                closure_errors.append(
                    f"{closure_path.relative_to(ROOT)}: consumer-relative action is not release-vendored: {reference}"
                )
                continue
            prefix = "tinyland-inc/ci-templates/.github/actions/"
            if reference.startswith(prefix):
                action_ref = reference.removeprefix(prefix)
                if "@" not in action_ref:
                    closure_errors.append(
                        f"{closure_path.relative_to(ROOT)}: internal action has no release ref: {reference}"
                    )
                    continue
                action_name, release_ref = action_ref.rsplit("@", maxsplit=1)
                if release_ref != RUST_BAZEL_RELEASE:
                    closure_errors.append(
                        f"{closure_path.relative_to(ROOT)}: internal action {action_name} must use @{RUST_BAZEL_RELEASE}"
                    )
                action_file = ROOT / ".github/actions" / action_name / "action.yml"
                if not action_file.is_file():
                    closure_errors.append(
                        f"{closure_path.relative_to(ROOT)}: missing internal action {action_file.relative_to(ROOT)}"
                    )
                    continue
                internal_actions.add(action_name)
                closure_queue.append(action_file)
                continue
            if "@" not in reference:
                closure_errors.append(
                    f"{closure_path.relative_to(ROOT)}: external action has no immutable ref: {reference}"
                )
                continue
            _action_name, release_ref = reference.rsplit("@", maxsplit=1)
            if not re.fullmatch(r"[0-9a-f]{40}", release_ref):
                closure_errors.append(
                    f"{closure_path.relative_to(ROOT)}: external action must use a full commit SHA: {reference}"
                )
            external_actions.add(reference)

    expected_internal_actions = {
        "cache-attachment-validate",
        "rust-bazel-binary-custody",
        "rust-bazel-contract",
        "rust-bazel-preflight",
    }
    if internal_actions != expected_internal_actions:
        closure_errors.append(
            "Rust+Bazel internal action closure changed: "
            f"expected {sorted(expected_internal_actions)}, got {sorted(internal_actions)}"
        )
    expected_external_actions = {f"actions/checkout@{RUST_BAZEL_CHECKOUT_SHA}"}
    if external_actions != expected_external_actions:
        closure_errors.append(
            "Rust+Bazel external action closure changed: "
            f"expected {sorted(expected_external_actions)}, got {sorted(external_actions)}"
        )
    for error in closure_errors:
        print(error, file=sys.stderr)
        ok = False

    default_false_inputs = ("enabled", "cache_enabled", "trusted_cache_upload")
    for input_name in default_false_inputs:
        block = re.search(
            rf"\n      {re.escape(input_name)}:\n(?:.*\n)*?        default: (\w+)\n",
            workflow,
        )
        if not block or block.group(1) != "false":
            print(
                f"{workflow_path.relative_to(ROOT)}: {input_name} must default false",
                file=sys.stderr,
            )
            ok = False

    required_workflow_snippets = [
        # TIN-3914: the admission job runs on the estate base capability
        # class, never a GitHub-hosted runner. It stays a bare label (not a
        # group mapping) because it validates runner_group before any
        # group-routed lane is scheduled.
        "runs-on: tinyland-nix",
        "repository_private: ${{ github.event.repository.private }}",
        "head_repository: ${{ github.event.pull_request.head.repo.full_name || '' }}",
        "timeout_minutes: ${{ inputs.timeout_minutes }}",
        "max_parallel: ${{ inputs.max_parallel }}",
        "rust-bazel-preflight@v2.14.0",
        "rust-bazel-binary-custody@v2.14.0",
        "steps.bazelisk-custody.outputs.path",
        "needs: trust-gate",
        'default: "[]"',
        "lane: ${{ fromJSON(needs.trust-gate.outputs.platform_matrix_json) }}",
        "group: ${{ inputs.runner_group }}",
        "labels: ${{ matrix.lane.runner_labels }}",
        "lane_name: ${{ matrix.lane.name }}",
        "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
        "rust-bazel-contract@v2.14.0",
        "cache-attachment-validate@v2.14.0",
        "github.ref_protected",
        "trusted_cache_upload: ${{ inputs.trusted_cache_upload }}",
        "cache_substrate_mode: ${{ inputs.cache_substrate_mode }}",
        "cache_endpoint: ${{ inputs.cache_enabled && secrets.GF_BAZEL_REMOTE_CACHE || '' }}",
        "cache_read_header_present: ${{ secrets.GF_BAZEL_REMOTE_CACHE_READ_HEADER != '' }}",
        "cache_write_header_present: ${{ secrets.GF_BAZEL_REMOTE_CACHE_WRITE_HEADER != '' }}",
        "cache_headers_distinct: ${{ secrets.GF_BAZEL_REMOTE_CACHE_READ_HEADER != secrets.GF_BAZEL_REMOTE_CACHE_WRITE_HEADER }}",
        "GF_BAZEL_REMOTE_UPLOAD: ${{ steps.contract.outputs.cache_upload }}",
        "secrets.GF_BAZEL_REMOTE_CACHE_READ_HEADER",
        "secrets.GF_BAZEL_REMOTE_CACHE_WRITE_HEADER",
        "steps.contract.outputs.cache_upload == 'true' && secrets.GF_BAZEL_REMOTE_CACHE_WRITE_HEADER",
        '--remote_upload_local_results="$GF_BAZEL_REMOTE_UPLOAD"',
        "remote_args=(--remote_executor=)",
        'BAZEL_REMOTE_EXECUTOR: ""',
        "remote_args+=(--remote_cache= --remote_upload_local_results=false)",
        '"$BAZELISK_DRIVER" mod deps --lockfile_mode=update',
        '"$BAZELISK_DRIVER" "$command"',
        "--lockfile_mode=error",
        "BAZELISK_DRIVER: ${{ steps.contract.outputs.bazelisk_driver }}",
        "CI_BAZEL_HOME: ${{ steps.contract.outputs.bazel_home }}",
        "CI_BAZELISK_BIN: ${{ steps.bazelisk-custody.outputs.path }}",
        "CI_BAZEL_VERSION: ${{ steps.contract.outputs.bazel_version }}",
        "dependency_authorities=(MODULE.bazel.lock Cargo.lock cargo-bazel-lock.json)",
        'run_group "rustfmt" test',
        'run_group "clippy" test',
        'run_group "application build" build',
        'run_group "unit tests" test',
        'run_group "integration tests" test',
        'run_group "packages" build',
        "Bzlmod or crate-universe authority changed during the authoritative target suite",
    ]
    for snippet in required_workflow_snippets:
        if snippet not in workflow:
            print(
                f"{workflow_path.relative_to(ROOT)}: missing Rust+Bazel contract snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    custody_step = workflow.find(
        "      - name: Validate trusted Bazelisk before caller checkout\n"
    )
    checkout_step = workflow.find("      - name: Check out exact caller revision\n")
    if custody_step < 0 or checkout_step < 0 or custody_step >= checkout_step:
        print(
            f"{workflow_path.relative_to(ROOT)}: binary custody must run before caller checkout",
            file=sys.stderr,
        )
        ok = False

    required_contract_snippets = [
        'OS_MAP = {"darwin": "macOS", "linux": "Linux"}',
        'ARCH_MAP = {"aarch64": "ARM64", "x86_64": "X64"}',
        "LANE_NAME_RE = re.compile",
        "RUNNER_GROUP_RE = re.compile",
        'ADMITTED_RUNNER_GROUPS = {"tinyland-infra"}',
        "ORG_CAPABILITY_RE = re.compile",
        "BAZEL_PLATFORM_MAP = {",
        "validate_bazel_platform",
        "cache_upload_allowed",
        "validate_cache_authority",
        "validate_caller_admission",
        "bounded_integer",
        "validate_matrix_contract",
        'target_name in {"all", "all-targets"}',
        '"cargo-bazel-lock.json",',
        "maximum=64",
        "required workspace file is not tracked",
        "workspace .bazeliskrc is not admitted",
        "BAZELISK_HOME_DARWIN",
        "CARGO_BAZEL_GENERATOR_URL",
        "CARGO_BAZEL_REPIN_ONLY",
    ]
    for snippet in required_contract_snippets:
        if snippet not in contract:
            print(
                f"{contract_path.relative_to(ROOT)}: missing fail-closed snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    for snippet in (
        "-u XDG_CACHE_HOME",
        'XDG_CACHE_HOME="$CI_BAZEL_HOME/xdg-cache"',
        '--output_user_root="$CI_BAZEL_HOME/bazel-output"',
    ):
        if snippet not in driver:
            print(
                f"{driver_path.relative_to(ROOT)}: missing job-scoped Bazel state snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    for snippet in (
        "TINYLAND_CI_BAZELISK_BIN",
        "STORE_BASENAME_RE",
        "path.resolve(strict=True) != path",
        "stat.S_IMODE(metadata.st_mode) & 0o022",
        "required_uid: int = 0",
        "rust-bazel binary custody self-test passed",
    ):
        if snippet not in custody_contract:
            print(
                f"{custody_contract_path.relative_to(ROOT)}: missing custody snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False
    if "custody.py" not in custody_action:
        print(
            f"{custody_action_path.relative_to(ROOT)}: custody action does not execute its contract",
            file=sys.stderr,
        )
        ok = False
    for snippet in (
        "value: ${{ steps.custody.outputs.path }}",
        '--github-output "$GITHUB_OUTPUT"',
    ):
        if snippet not in custody_action:
            print(
                f"{custody_action_path.relative_to(ROOT)}: missing custody output wiring: {snippet}",
                file=sys.stderr,
            )
            ok = False
    if 'handle.write(f"path={path}\\n")' not in custody_contract:
        print(
            f"{custody_contract_path.relative_to(ROOT)}: canonical path is not written to the action output",
            file=sys.stderr,
        )
        ok = False

    required_docs_snippets = [
        "opt-in, default-off",
        "does not claim a four-platform",
        "tinyland-infra",
        "same-repository",
        "@v2.14.0",
        "github.ref_protected == true",
        "cache-first",
        "release publication remains a",
        "TINYLAND_CI_BAZELISK_BIN",
        "before caller checkout",
        "not consult PATH for Bazelisk",
        "XDG_CACHE_HOME",
        "--output_user_root",
    ]
    for snippet in required_docs_snippets:
        if snippet not in docs:
            print(
                f"{docs_path.relative_to(ROOT)}: missing public contract snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    forbidden_workflow_snippets = [
        "GF_BAZEL_REMOTE_HEADER",
        "GF_BAZEL_CREDENTIAL_HELPER",
        # TIN-3914: reject the whole GitHub-hosted label families, not the three
        # `-latest` aliases that happened to be in use. `ubuntu-24.04` slipped
        # past the old list for exactly that reason.
        "ubuntu-",
        "macos-",
        "windows-",
        "cargo build",
        "cargo test",
        "//...",
    ]
    for snippet in forbidden_workflow_snippets:
        if snippet in workflow:
            print(
                f"{workflow_path.relative_to(ROOT)}: forbidden Rust+Bazel workflow snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False
    if "--remote_executor" in workflow.replace("--remote_executor=", ""):
        print(
            f"{workflow_path.relative_to(ROOT)}: remote executor may only appear as an explicit empty override",
            file=sys.stderr,
        )
        ok = False
    if "BAZEL_REMOTE_EXECUTOR" in workflow.replace('BAZEL_REMOTE_EXECUTOR: ""', ""):
        print(
            f"{workflow_path.relative_to(ROOT)}: inherited executor authority may only be cleared with an explicit empty step env",
            file=sys.stderr,
        )
        ok = False
    if re.search(
        r"tinyland-inc/ci-templates/\.github/actions/[^@\s]+@v2(?:\s|$)", workflow
    ):
        print(
            f"{workflow_path.relative_to(ROOT)}: floating internal action reference",
            file=sys.stderr,
        )
        ok = False
    native_job_header = workflow.split("\n  native:\n", maxsplit=1)[1].split(
        "\n    steps:\n", maxsplit=1
    )[0]
    if "secrets.GF_BAZEL" in native_job_header:
        print(
            f"{workflow_path.relative_to(ROOT)}: cache secrets must be step-scoped",
            file=sys.stderr,
        )
        ok = False
    for secret_name in (
        "secrets.GF_BAZEL_REMOTE_CACHE_READ_HEADER",
        "secrets.GF_BAZEL_REMOTE_CACHE_WRITE_HEADER",
    ):
        if workflow.count(secret_name) != 3:
            print(
                f"{workflow_path.relative_to(ROOT)}: {secret_name} must have one presence check, one equality check, and one step-scoped materialization",
                file=sys.stderr,
            )
            ok = False
    if (
        "--matrix-preflight" not in preflight_action
        or "contract.py" not in preflight_action
    ):
        print(
            f"{preflight_action_path.relative_to(ROOT)}: preflight must use the release-vendored matrix contract",
            file=sys.stderr,
        )
        ok = False
    if re.search(r"(?:grpc|grpcs|http|https)://", workflow):
        print(
            f"{workflow_path.relative_to(ROOT)}: workflow source must remain endpoint-free",
            file=sys.stderr,
        )
        ok = False
    if (
        "contract.py" not in action
        or "required_bazel_major" not in action
        or "cache_upload" not in action
        or "runner_group" not in action
    ):
        print(
            f"{action_path.relative_to(ROOT)}: action must invoke the pinned Bazel contract",
            file=sys.stderr,
        )
        ok = False

    if not ok:
        return 1
    print("Rust+Bazel application workflow contract documented and guarded")
    return 0


# TIN-3914. The lanes schema validates CONSUMER data, and `lanes-load` feeds
# `runnerClass` into spoke-ci's `matrix.lane.runner_class`, i.e. straight into
# `runs-on`. Until v3.0.0 the schema carried an explicit `{"const":
# "ubuntu-latest"}` arm, so a consumer could route a build job onto GitHub's
# fleet with this repo's own schema approving it — and none of the
# workflow-facing gates could see it: `lint-runs-on.rb` reads workflow text,
# and the textual backstop only reads files, not what a regex ADMITS.
#
# This check is semantic, not textual: it asserts no GitHub-hosted label is
# REPRESENTABLE as a runnerClass, by executing every accept-arm against hostile
# and legitimate label sets. A future arm that re-opens the hole in some new
# spelling fails here even if it never writes a hosted label down.
HOSTED_LABEL_RE = re.compile(r"^(ubuntu|macos|windows)-", re.IGNORECASE)

HOSTILE_RUNNER_CLASSES = (
    "ubuntu-latest",
    "Ubuntu-Latest",
    "ubuntu-24.04",
    "ubuntu-latest-4-cores",
    "ubuntu-22.04-arm",
    "macos-15",
    "MacOS-Latest",
    "windows-2022",
    "windows-11-arm",
)

LEGITIMATE_RUNNER_CLASSES = (
    "tinyland-nix",
    "tinyland-nix-heavy",
    "tinyland-nix-kvm",
    "tinyland-docker",
    "tinyland-dind",
    "great-falls-tool-bus-nix",
)


def _collect_accept_arms(node: object, literals: list, patterns: list, open_strings: list) -> None:
    if not isinstance(node, dict):
        return
    if "const" in node:
        literals.append(node["const"])
    if "enum" in node:
        literals.extend(node["enum"])
    if "pattern" in node:
        patterns.append(node["pattern"])
    elif node.get("type") == "string" and "const" not in node and "enum" not in node:
        # A bare string arm accepts anything, hosted labels included.
        open_strings.append(node)
    for combinator in ("anyOf", "oneOf", "allOf"):
        for child in node.get(combinator, []):
            _collect_accept_arms(child, literals, patterns, open_strings)


def check_lanes_schema_runner_class() -> int:
    schema_path = ROOT / "schemas/lanes.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    rel = schema_path.relative_to(ROOT)
    node = schema.get("$defs", {}).get("runnerClass")
    ok = True

    if not isinstance(node, dict):
        print(f"{rel}: $defs.runnerClass is missing", file=sys.stderr)
        return 1

    literals: list = []
    patterns: list = []
    open_strings: list = []
    _collect_accept_arms(node, literals, patterns, open_strings)

    if open_strings:
        print(
            f"{rel}: runnerClass has an unconstrained string arm; it would admit any runner label",
            file=sys.stderr,
        )
        ok = False
    if not literals and not patterns:
        print(f"{rel}: runnerClass constrains nothing", file=sys.stderr)
        ok = False

    for literal in literals:
        if HOSTED_LABEL_RE.match(str(literal)):
            print(
                f"{rel}: runnerClass sanctions GitHub-hosted label {literal!r}; "
                "consumer lanes.json feeds this into spoke-ci's runs-on (TIN-3914)",
                file=sys.stderr,
            )
            ok = False

    compiled = []
    for pattern in patterns:
        try:
            compiled.append((pattern, re.compile(pattern)))
        except re.error as exc:
            print(f"{rel}: runnerClass pattern {pattern!r} does not compile: {exc}", file=sys.stderr)
            ok = False
    for pattern, regex in compiled:
        for label in HOSTILE_RUNNER_CLASSES:
            if regex.search(label):
                print(
                    f"{rel}: runnerClass pattern {pattern!r} admits GitHub-hosted label {label!r} "
                    "(TIN-3914)",
                    file=sys.stderr,
                )
                ok = False

    # Guard the other direction too: a pattern tightened until it rejects the
    # capability classes would "pass" this check while breaking every consumer.
    for label in LEGITIMATE_RUNNER_CLASSES:
        admitted = label in [str(literal) for literal in literals] or any(
            regex.search(label) for _pattern, regex in compiled
        )
        if not admitted:
            print(
                f"{rel}: runnerClass no longer admits capability class {label!r}",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print(
        "lanes schema runnerClass admits capability classes only "
        f"({len(HOSTILE_RUNNER_CLASSES)} hostile labels rejected, "
        f"{len(LEGITIMATE_RUNNER_CLASSES)} capability classes accepted)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "check",
        choices=[
            "manifest",
            "internal-refs",
            "js-bazel-runner-contract",
            "flywheel-reapi-proof-contract",
            "cache-backed-optin-contract",
            "rust-bazel-application-contract",
            "lanes-schema-runner-class",
        ],
    )
    args = parser.parse_args()

    if args.check == "manifest":
        return validate_manifest()
    if args.check == "js-bazel-runner-contract":
        return check_js_bazel_package_runner_contract()
    if args.check == "flywheel-reapi-proof-contract":
        return check_flywheel_reapi_proof_contract()
    if args.check == "cache-backed-optin-contract":
        return check_cache_backed_optin_contract()
    if args.check == "rust-bazel-application-contract":
        return check_rust_bazel_application_contract()
    if args.check == "lanes-schema-runner-class":
        return check_lanes_schema_runner_class()
    return check_internal_refs()


if __name__ == "__main__":
    raise SystemExit(main())
