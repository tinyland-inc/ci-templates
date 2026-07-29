#!/usr/bin/env python3
"""Repository-local validation helpers for tinyland-inc/ci-templates."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]


def action_run_input_interpolations(
    action_path: pathlib.Path,
) -> list[tuple[int, str]]:
    """Return composite steps whose parsed run scalar contains an expression."""

    ruby = r"""
doc = YAML.load_file(ARGV.fetch(0))
steps = doc.fetch("runs").fetch("steps")
runs = []
steps.each_with_index do |step, index|
  next unless step.key?("run")
  runs << {
    "index" => index,
    "name" => (step["name"] || "step-#{index}"),
    "run" => step.fetch("run").to_s,
  }
end
puts JSON.generate(runs)
"""
    result = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e", ruby, str(action_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown Ruby YAML parse error"
        raise ValueError(f"could not parse action run scalars: {detail}")

    parsed_runs = json.loads(result.stdout)
    return [
        (int(step["index"]), str(step["name"]))
        for step in parsed_runs
        if "${{" in str(step["run"])
    ]


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
    action_pattern = re.compile(r"tinyland-inc/ci-templates/\.github/actions/([^@\s]+)@v2\b")
    main_pattern = re.compile(r"tinyland-inc/ci-templates/.*@main")

    for path in sorted((ROOT / ".github").glob("**/*.yml")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for action in action_pattern.findall(text):
            action_yml = ROOT / ".github/actions" / action / "action.yml"
            if not action_yml.exists():
                print(f"{rel}: missing internal action {action_yml.relative_to(ROOT)}", file=sys.stderr)
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


def check_blahaj_dispatch_receiver_contract() -> int:
    """Guard exact-receiver containment for token-bearing Blahaj dispatchers."""

    action_paths = [
        ROOT / ".github/actions/lane-dispatch/action.yml",
        ROOT / ".github/actions/lane-reap/action.yml",
        ROOT / ".github/actions/lane-ttl-reap/action.yml",
        ROOT / ".github/actions/public-preview-dispatch/action.yml",
    ]
    helper_path = ROOT / "scripts/blahaj-repository-dispatch.sh"
    validator_path = ROOT / "scripts/validate-blahaj-dispatch-receiver.sh"
    selftest_path = ROOT / "scripts/blahaj-dispatch-receiver-selftest.sh"
    shell_input_selftest_path = (
        ROOT / "scripts/blahaj-dispatch-shell-input-selftest.sh"
    )
    ok = True

    for path in (
        *action_paths,
        helper_path,
        validator_path,
        selftest_path,
        shell_input_selftest_path,
    ):
        if not path.exists():
            print(f"missing {path.relative_to(ROOT)}", file=sys.stderr)
            ok = False
    if not ok:
        return 1

    required_action_snippets = [
        "default: tinyland-inc/blahaj",
        "DISPATCH_HELPER: ${{ github.action_path }}/../../../scripts/blahaj-repository-dispatch.sh",
        'bash "${DISPATCH_HELPER}" "${BLAHAJ_REPOSITORY}" "${PAYLOAD_PATH}"',
        "BLAHAJ_REPOSITORY: ${{ inputs.blahaj_repository }}",
        "PAYLOAD_PATH: ${{ steps.build.outputs.payload_path }}",
        "GH_TOKEN: ${{ inputs.dispatch_token }}",
    ]
    for path in action_paths:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for snippet in required_action_snippets:
            if snippet not in text:
                print(
                    f"{rel}: missing exact-receiver dispatch snippet: {snippet}",
                    file=sys.stderr,
                )
                ok = False
        if "gh api " in text or "/dispatches" in text:
            print(
                f"{rel}: embeds a dispatch endpoint instead of using the validated helper",
                file=sys.stderr,
            )
            ok = False
        if text.count("${{ inputs.blahaj_repository }}") != 1:
            print(
                f"{rel}: blahaj_repository must enter the dispatch step only through "
                "the quoted environment binding",
                file=sys.stderr,
            )
            ok = False
        try:
            interpolated_steps = action_run_input_interpolations(path)
        except (ValueError, json.JSONDecodeError) as err:
            print(f"{rel}: {err}", file=sys.stderr)
            ok = False
            continue
        for step_index, step_name in interpolated_steps:
            print(
                f"{rel}: step {step_index} ({step_name}) contains a GitHub "
                "expression in parsed run source instead of an env binding",
                file=sys.stderr,
            )
            ok = False

    helper = helper_path.read_text(encoding="utf-8")
    validator_call = (
        'bash "${script_dir}/validate-blahaj-dispatch-receiver.sh" "${receiver}"'
    )
    dispatch_call = 'gh api "/repos/${receiver}/dispatches"'
    validator_index = helper.find(validator_call)
    dispatch_index = helper.find(dispatch_call)
    if validator_index < 0:
        print(
            f"{helper_path.relative_to(ROOT)}: missing exact receiver validator call",
            file=sys.stderr,
        )
        ok = False
    if dispatch_index < 0:
        print(
            f"{helper_path.relative_to(ROOT)}: missing repository_dispatch call",
            file=sys.stderr,
        )
        ok = False
    if validator_index >= 0 and dispatch_index >= 0 and validator_index >= dispatch_index:
        print(
            f"{helper_path.relative_to(ROOT)}: receiver validation must precede gh api",
            file=sys.stderr,
        )
        ok = False
    if helper.count("gh api ") != 1:
        print(
            f"{helper_path.relative_to(ROOT)}: dispatch helper must have exactly one gh api call",
            file=sys.stderr,
        )
        ok = False

    validator = validator_path.read_text(encoding="utf-8")
    for snippet in (
        'readonly expected_receiver="tinyland-inc/blahaj"',
        'if [[ "${receiver}" != "${expected_receiver}" ]]',
    ):
        if snippet not in validator:
            print(
                f"{validator_path.relative_to(ROOT)}: missing fail-closed snippet: {snippet}",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print("Blahaj repository_dispatch receiver validation precedes every dispatch")
    return 0


def selftest_action_run_scalar_guard() -> int:
    """Mutation-test rejection of every GitHub-expression spelling."""

    clean_action = """\
name: parsed-run-selftest
runs:
  using: composite
  steps:
    - name: probe
      shell: bash
      run: SAFE_RUN_SOURCE
"""
    mutations = {
        "clean": ("echo safe", False),
        "inline-dot": ('echo "${{ inputs.receiver }}"', True),
        "block-dot": ('|-\n        echo "${{inputs.receiver}}"', True),
        "inline-bracket": ('echo "${{ inputs[\'receiver\'] }}"', True),
        "block-bracket": ('|-\n        echo "${{ inputs[\'receiver\'] }}"', True),
        "inline-nested": (
            'echo "${{ fromJSON(toJSON(inputs))[\'receiver\'] }}"',
            True,
        ),
        "block-nested": (
            '|-\n        echo "${{ fromJSON(toJSON(inputs))[\'receiver\'] }}"',
            True,
        ),
    }
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        for name, (replacement, must_reject) in mutations.items():
            action_path = tmp / f"{name}.yml"
            action_path.write_text(
                clean_action.replace("SAFE_RUN_SOURCE", replacement),
                encoding="utf-8",
            )
            findings = action_run_input_interpolations(action_path)
            rejected = bool(findings)
            if rejected != must_reject:
                verdict = "reject" if must_reject else "accept"
                print(
                    f"run-scalar guard did not {verdict} {name} mutation",
                    file=sys.stderr,
                )
                return 1

    print("parsed action run-scalar guard rejects inline and block GitHub expressions")
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
            "flywheel-reapi-proof-contract",
            "blahaj-dispatch-receiver-contract",
            "blahaj-dispatch-run-scalar-selftest",
            "cache-backed-optin-contract",
        ],
    )
    args = parser.parse_args()

    if args.check == "manifest":
        return validate_manifest()
    if args.check == "js-bazel-runner-contract":
        return check_js_bazel_package_runner_contract()
    if args.check == "flywheel-reapi-proof-contract":
        return check_flywheel_reapi_proof_contract()
    if args.check == "blahaj-dispatch-receiver-contract":
        return check_blahaj_dispatch_receiver_contract()
    if args.check == "blahaj-dispatch-run-scalar-selftest":
        return selftest_action_run_scalar_guard()
    if args.check == "cache-backed-optin-contract":
        return check_cache_backed_optin_contract()
    return check_internal_refs()


if __name__ == "__main__":
    raise SystemExit(main())
