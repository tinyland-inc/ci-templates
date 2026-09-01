#!/usr/bin/env python3
"""Repository-local validation helpers for tinyland-inc/ci-templates."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import shlex
import subprocess
import sys
from collections import Counter


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


def _load_manifest_router():
    """Import the routing half of scripts/manifest-schema-validate.py.

    The version -> schema-filename mapping lives in exactly one file. This
    check used to carry a SECOND copy of it, spelled as a hardcoded v1 path —
    the same defect the composite action shipped, one directory over. It made
    `validate-ci-templates.py manifest` print "valid" for a v1 manifest checked
    against a schema, and it would answer a v2 manifest with the `const 1` wall
    the action was fixed to stop emitting. Importing the router instead of
    re-deriving it is what keeps the two from drifting apart again.
    """
    path = ROOT / "scripts" / "manifest-schema-validate.py"
    spec = importlib.util.spec_from_file_location("manifest_schema_validate", path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging error
        raise RuntimeError(f"cannot load the manifest router from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_manifest() -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("python jsonschema is unavailable", file=sys.stderr)
        return 2

    router = _load_manifest_router()
    manifest_path = ROOT / "tinyland.repo.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    try:
        schema_name = router.resolve_schema_name(json.loads(manifest_text))
    except router.UnsupportedSchemaVersion as exc:
        print(f"{manifest_path.relative_to(ROOT)}: {exc}", file=sys.stderr)
        return 1
    schema_path = ROOT / "schemas" / schema_name
    if not schema_path.is_file():
        print(
            f"{manifest_path.relative_to(ROOT)} routes to schemas/{schema_name}, which is "
            "not present in this checkout — the manifest was not validated against anything",
            file=sys.stderr,
        )
        return 1
    print(f"tinyland.repo.json -> schemas/{schema_name}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_text)
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
}


def check_v4_action_client_surface() -> bool:
    """Assert the thin v4 workflow delegates execution to the compiled client.

    This replaces the larger inline OCI/proxy assertion family. Retire it when
    the typed workflow-effect contract directly enforces this boundary.
    """

    path = ROOT / ".github/workflows/spoke-ci-v4.yml"
    if not path.is_file():
        print(f"{path.relative_to(ROOT)}: missing thin v4 action workflow", file=sys.stderr)
        return False

    document = path.read_text(encoding="utf-8")
    call_surface = document.split("\npermissions:\n", maxsplit=1)[0]
    failures: list[str] = []

    required = {
        "ref: ${{ github.sha }}": "exact caller-context source checkout",
        "SOURCE_SHA: ${{ github.sha }}": "exact caller-context source identity",
        "ACTION_NAME: ${{ inputs.action_name }}": "caller-selected action identity",
        "/usr/local/bin/gf-action-client run": "compiled action client",
        "--plan .github/lanes.json": "canonical action plan",
        '--action "$ACTION_NAME"': "one named action per invocation",
        '--source-sha "$SOURCE_SHA"': "source identity passed to the client",
    }
    for snippet, claim in required.items():
        if snippet not in document:
            failures.append(f"missing {claim}")

    if re.findall(r"^      ([a-z_][a-z0-9_]*):$", call_surface, re.MULTILINE) != [
        "action_name"
    ]:
        failures.append("workflow_call must expose only the checked-in action name")
    if document.count("id-token: write") != 1:
        failures.append("the thin dispatcher must carry exactly one OIDC permission")
    if re.findall(
        r"^  ([a-z_][a-z0-9_-]*):$",
        document.partition("\njobs:\n")[2],
        re.MULTILINE,
    ) != ["action-fabric"]:
        failures.append("v4 action fabric must remain one thin job identity")

    for forbidden in (
        "executionPool",
        "runner_class",
        "GF_REAPI_",
        "BAZEL_REMOTE_",
        "gloriousflywheel-rbe-",
        "@v4.0.0",
        "packages: write",
        "contents: write",
        "git push",
        "curl ",
        "python3",
        "mktemp",
        "trap ",
        "proxy",
        "fallback",
    ):
        if forbidden in document:
            failures.append(f"thin v4 dispatcher contains forbidden orchestration: {forbidden}")

    if failures:
        for failure in failures:
            print(f"{path.relative_to(ROOT)}: {failure}", file=sys.stderr)
        return False
    print("v4 workflow is a thin compiled-client dispatcher")
    return True

def check_internal_refs() -> int:
    ok = check_v4_action_client_surface()
    action_pattern = re.compile(
        r"tinyland-inc/ci-templates/\.github/actions/([^@\s]+)@([^\s#]+)"
    )
    main_pattern = re.compile(r"tinyland-inc/ci-templates/.*@main")
    exact_release = re.compile(r"\Av\d+\.\d+\.\d+\Z")

    for path in sorted((ROOT / ".github").glob("**/*.yml")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        expected_release_line = CURRENT_RELEASE_LINE
        for action, ref in action_pattern.findall(text):
            action_yml = ROOT / ".github/actions" / action / "action.yml"
            if not action_yml.exists():
                print(f"{rel}: missing internal action {action_yml.relative_to(ROOT)}", file=sys.stderr)
                ok = False
            if exact_release.match(ref) or ref == expected_release_line:
                continue
            if str(rel) in STALE_INTERNAL_REF_FILES:
                continue
            print(
                f"{rel}: internal action {action}@{ref} is not on the current release line "
                f"@{expected_release_line} and is not an exact release pin; a stale floating "
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
    print(f"internal action refs resolve and track their release line (or an exact release pin)")
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


def check_vendored_schema_provenance() -> int:
    """Assert every vendored schema still matches its recorded digest.

    This gate is deliberately HERMETIC: it compares the vendored bytes to the
    digests recorded in VENDORED.json, and does NOT reach out to site.scaffold.
    It covers every `schemas/*.schema.json`; upstream freshness remains a
    separate non-blocking question, and a `drifted` entry is reported rather
    than failed because reconciling it changes the consumer contract.

    STATE VOCABULARY, and why each arm is asserted rather than recorded:

      identical  the vendored bytes equal the upstream bytes; `upstream_sha256`
                 must equal `sha256`, or the record is claiming a match it does
                 not have
      drifted    a known divergence; `upstream_sha256` must be present and must
                 DIFFER, or "drifted" is describing a file that isn't
      unsourced  the `$id` names a site.scaffold path that does not exist at
                 the recorded revision, so there is nothing to compare and
                 `upstream_sha256` must be absent

    Before this, `state` and `upstream_sha256` were recorded and never checked:
    an entry could say `identical` next to an `upstream_sha256` of 64 zeros and
    pass silently. `state` is the field an operator reads to sequence the v1
    de-fork, so unasserted metadata there is a wrong answer waiting to be
    trusted. The digest equality is free and offline; what stays advisory is
    `source_revision` itself, which only a network call could verify and which
    this check deliberately will not make.
    """

    record_path = ROOT / "schemas" / "VENDORED.json"
    if not record_path.is_file():
        print(f"::error::missing vendoring record at {record_path}", file=sys.stderr)
        return 1

    record = json.loads(record_path.read_text(encoding="utf-8"))
    entries = record.get("files", [])
    if not entries:
        # An empty record would pass every loop below while asserting nothing.
        print(
            "::error::schemas/VENDORED.json records no files; it cannot vouch for anything",
            file=sys.stderr,
        )
        return 1

    failures = 0

    # Entry shape first, by name. A malformed record used to reach
    # `entry["sha256"]` and die on an uncaught KeyError traceback -- it failed
    # closed, but every other failure path in this function emits a `::error::`
    # an operator can act on, and a stack trace is not one.
    required_keys = ("vendored", "source", "sha256", "state")
    well_formed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            print(
                f"::error file=schemas/VENDORED.json::files[{index}] is not an object",
                file=sys.stderr,
            )
            failures += 1
            continue
        absent = [key for key in required_keys if key not in entry]
        if absent:
            name = entry.get("vendored", f"files[{index}]")
            print(
                f"::error file=schemas/VENDORED.json::{name} is missing required "
                f"key(s): {', '.join(absent)}. Every entry needs {', '.join(required_keys)}.",
                file=sys.stderr,
            )
            failures += 1
            continue
        well_formed.append(entry)

    recorded = {entry["vendored"] for entry in well_formed}
    on_disk = {
        f"schemas/{path.name}"
        for path in sorted((ROOT / "schemas").glob("*.schema.json"))
    }
    for missing in sorted(on_disk - recorded):
        # A new vendored schema that nobody recorded is the exact hole this
        # gate exists to close, so it must not be silently out of scope.
        print(
            f"::error file={missing}::schema in schemas/ is not recorded in "
            "schemas/VENDORED.json, so nothing pins it to a source revision. Add an "
            "entry with its source path, sha256 and state (use state=unsourced if "
            "its $id names a path that does not exist upstream).",
            file=sys.stderr,
        )
        failures += 1

    for entry in well_formed:
        vendored = ROOT / entry["vendored"]
        if not vendored.is_file():
            print(f"::error::vendored schema missing: {entry['vendored']}", file=sys.stderr)
            failures += 1
            continue
        actual = hashlib.sha256(vendored.read_bytes()).hexdigest()
        expected = entry["sha256"]
        if actual != expected:
            print(
                f"::error file={entry['vendored']}::vendored schema does not match "
                f"schemas/VENDORED.json (recorded {expected[:16]}, found {actual[:16]}). "
                "Re-vendor from the recorded source revision instead of hand-editing "
                "the copy, and update the digest in the same change.",
                file=sys.stderr,
            )
            failures += 1
            continue

        # The state claim itself, asserted against the digests beside it. These
        # are pure record-internal consistency checks -- offline, no network --
        # and they are what turns `state` from a comment into a fact.
        state = entry["state"]
        upstream = entry.get("upstream_sha256")
        if state == "identical":
            if upstream != actual:
                print(
                    f"::error file={entry['vendored']}::recorded state=identical but "
                    f"upstream_sha256 ({(upstream or '(absent)')[:16]}) does not equal the "
                    f"vendored digest ({actual[:16]}). Either the copy is drifted and the "
                    "state is wrong, or the recorded upstream digest is.",
                    file=sys.stderr,
                )
                failures += 1
                continue
        elif state == "drifted":
            if not upstream:
                print(
                    f"::error file={entry['vendored']}::recorded state=drifted without an "
                    "upstream_sha256, so the divergence it claims is unmeasurable.",
                    file=sys.stderr,
                )
                failures += 1
                continue
            if upstream == actual:
                print(
                    f"::error file={entry['vendored']}::recorded state=drifted but "
                    "upstream_sha256 equals the vendored digest -- the copy matches its "
                    "source, so record it as identical rather than carrying a divergence "
                    "that no longer exists.",
                    file=sys.stderr,
                )
                failures += 1
                continue
        elif state == "unsourced":
            if upstream:
                print(
                    f"::error file={entry['vendored']}::recorded state=unsourced but an "
                    "upstream_sha256 is present. Unsourced means no upstream file exists "
                    "to digest; if one does, record identical or drifted.",
                    file=sys.stderr,
                )
                failures += 1
                continue
        else:
            print(
                f"::error file={entry['vendored']}::unknown state {state!r}. Accepted: "
                "identical, drifted, unsourced.",
                file=sys.stderr,
            )
            failures += 1
            continue

        print(f"vendored ok: {entry['vendored']} ({state})")
        if state in ("drifted", "unsourced"):
            print(
                f"::notice file={entry['vendored']}::{state} against "
                f"{record['source_repository']}: {entry.get('state_note', '')}"
            )

    if failures:
        return 1
    counts = Counter(entry["state"] for entry in well_formed)
    summary = ", ".join(f"{counts[state]} {state}" for state in sorted(counts))
    print(
        f"all {len(well_formed)} schemas in schemas/ are recorded in "
        f"schemas/VENDORED.json and match their digests ({summary}; source "
        f"{record['source_repository']} @ {record['source_revision'][:12]}, "
        "revision itself advisory -- this check never leaves the checkout)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "check",
        choices=[
            "manifest",
            "vendored-schema-provenance",
            "internal-refs",
            "js-bazel-runner-contract",
            "flywheel-reapi-proof-contract",
            "cache-backed-optin-contract",
            "rust-bazel-application-contract",
        ],
    )
    args = parser.parse_args()

    if args.check == "manifest":
        return validate_manifest()
    if args.check == "vendored-schema-provenance":
        return check_vendored_schema_provenance()
    if args.check == "js-bazel-runner-contract":
        return check_js_bazel_package_runner_contract()
    if args.check == "flywheel-reapi-proof-contract":
        return check_flywheel_reapi_proof_contract()
    if args.check == "cache-backed-optin-contract":
        return check_cache_backed_optin_contract()
    if args.check == "rust-bazel-application-contract":
        return check_rust_bazel_application_contract()
    return check_internal_refs()


if __name__ == "__main__":
    raise SystemExit(main())
