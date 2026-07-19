#!/usr/bin/env python3
"""Repository-local validation helpers for tinyland-inc/ci-templates."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_workflow(path: pathlib.Path) -> dict:
    """Parse workflow YAML through the repository's existing Ruby/Psych toolchain."""

    result = subprocess.run(
        [
            "ruby",
            "-rjson",
            "-ryaml",
            "-e",
            "puts JSON.generate(YAML.load_file(ARGV.fetch(0)))",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"could not parse {path}")
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must parse to an object")
    return parsed


def workflow_events(workflow: dict) -> dict:
    """Psych may serialize YAML's plain `on` key as JSON key `true`."""

    events = workflow.get("on", workflow.get("true"))
    return events if isinstance(events, dict) else {}


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


def check_lane_status_namespace_contract() -> int:
    """Keep the v2 status migration explicit, opt-in, and truthfully named."""

    ci_path = ROOT / ".github/workflows/spoke-ci.yml"
    action_path = ROOT / ".github/actions/lane-status-check/action.yml"
    schema_path = ROOT / "schemas/lanes.schema.json"
    readme_path = ROOT / "README.md"
    ok = True

    try:
        ci = load_workflow(ci_path)
        action = load_workflow(action_path)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    inputs = workflow_events(ci).get("workflow_call", {}).get("inputs", {})
    status_input = inputs.get("lane_status_context_prefix")
    if not isinstance(status_input, dict) or status_input.get("default") != "ci/lane/":
        print(f"{ci_path.relative_to(ROOT)}: status input must default to ci/lane/", file=sys.stderr)
        ok = False

    steps = ci.get("jobs", {}).get("flywheel-build", {}).get("steps", [])
    status_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Post lane build status"
    ]
    expected_with = {
        "commit_sha": "${{ github.event.pull_request.head.sha || github.sha }}",
        "lane_name": "${{ matrix.lane.name }}",
        "state": "${{ job.status == 'success' && 'success' || 'failure' }}",
        "description": "${{ inputs.lane_status_context_prefix == 'ci/build/' && format('build ({0})', matrix.lane.name) || format('build-and-test ({0})', matrix.lane.name) }}",
        "context_prefix": "${{ inputs.lane_status_context_prefix == 'ci/build/' && 'ci/build/' || 'ci/lane/' }}",
    }
    if len(status_steps) != 1 or status_steps[0].get("with") != expected_with:
        print(f"{ci_path.relative_to(ROOT)}: active flywheel-build status step drifted", file=sys.stderr)
        ok = False

    action_input = action.get("inputs", {}).get("context_prefix")
    if not isinstance(action_input, dict) or action_input.get("default") != "ci/lane/":
        print(f"{action_path.relative_to(ROOT)}: action default must remain ci/lane/", file=sys.stderr)
        ok = False
    action_steps = action.get("runs", {}).get("steps", [])
    post_steps = [
        step
        for step in action_steps
        if isinstance(step, dict) and step.get("name") == "Post status"
    ]
    post_script = post_steps[0].get("run", "") if len(post_steps) == 1 else ""
    post_env = post_steps[0].get("env", {}) if len(post_steps) == 1 else {}
    namespace_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Validate lane status namespace"
    ]
    namespace_script = namespace_steps[0].get("run", "") if len(namespace_steps) == 1 else ""
    namespace_env = namespace_steps[0].get("env", {}) if len(namespace_steps) == 1 else {}
    if (
        namespace_env
        != {"LANE_STATUS_CONTEXT_PREFIX": "${{ inputs.lane_status_context_prefix }}"}
        or 'case "$LANE_STATUS_CONTEXT_PREFIX" in' not in namespace_script
        or "ci/lane/|ci/build/" not in namespace_script
    ):
        print(
            f"{ci_path.relative_to(ROOT)}: spoke caller must fail closed to approved status namespaces",
            file=sys.stderr,
        )
        ok = False

    required_script_snippets = [
        'context="${INPUT_CONTEXT_PREFIX}${INPUT_LANE_NAME}"',
        "${GITHUB_REPOSITORY}/statuses/${INPUT_COMMIT_SHA}",
    ]
    if any(snippet not in post_script for snippet in required_script_snippets):
        print(
            f"{action_path.relative_to(ROOT)}: status writer must avoid direct input interpolation",
            file=sys.stderr,
        )
        ok = False
    expected_input_env = {
        "GH_TOKEN": "${{ inputs.github_token }}",
        "INPUT_COMMIT_SHA": "${{ inputs.commit_sha }}",
        "INPUT_CONTEXT_PREFIX": "${{ inputs.context_prefix }}",
        "INPUT_DESCRIPTION": "${{ inputs.description }}",
        "INPUT_LANE_NAME": "${{ inputs.lane_name }}",
        "INPUT_STATE": "${{ inputs.state }}",
        "INPUT_TARGET_URL": "${{ inputs.target_url }}",
    }
    if post_env != expected_input_env:
        print(
            f"{action_path.relative_to(ROOT)}: status inputs must cross the shell boundary through env",
            file=sys.stderr,
        )
        ok = False
    if "${{ inputs." in post_script or "${{ github." in post_script:
        print(
            f"{action_path.relative_to(ROOT)}: status script interpolates untrusted expressions directly",
            file=sys.stderr,
        )
        ok = False

    required_snippets = {
        action_path: [
            "`ci/build/`",
            "`ci/lane/<name>`",
            "status name alone is not",
            "owner-overlay observer",
        ],
        schema_path: [
            "`ci/build/<name>`",
            "`ci/lane/<name>`",
            "legacy build-status name",
        ],
        readme_path: [
            "lane_status_context_prefix: ci/build/",
            "`ci/build/<name>`",
            "`ci/lane/<name>`",
            "does not prove",
            "flywheel-build results",
        ],
    }
    for path, snippets in required_snippets.items():
        text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        for snippet in snippets:
            if re.sub(r"\s+", " ", snippet) not in text:
                print(
                    f"{path.relative_to(ROOT)}: missing lane-status namespace snippet: {snippet}",
                    file=sys.stderr,
                )
                ok = False

    if not ok:
        return 1
    print("v2 lane-status namespace migration is explicit, opt-in, and truthfully documented")
    return 0


def check_default_branch_ruleset_contract() -> int:
    """Validate the source contract for guarded remote checks and branch rails."""

    ruleset_path = ROOT / ".github/rulesets/default-branch.json"
    actions_policy_path = ROOT / ".github/actions-policy.json"
    workflow_path = ROOT / ".github/workflows/validate.yml"
    release_path = ROOT / ".github/workflows/release.yml"
    ruleset = json.loads(ruleset_path.read_text(encoding="utf-8"))
    actions_policy = json.loads(actions_policy_path.read_text(encoding="utf-8"))
    try:
        workflow = load_workflow(workflow_path)
        release = load_workflow(release_path)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    ok = True

    expected_header = {
        "name": "main-signed-merge-lineage",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "exclude": [],
                "include": ["refs/heads/main"],
            }
        },
    }
    for key, expected in expected_header.items():
        if ruleset.get(key) != expected:
            print(
                f"{ruleset_path.relative_to(ROOT)}: {key} must be {expected!r}",
                file=sys.stderr,
            )
            ok = False

    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        print(f"{ruleset_path.relative_to(ROOT)}: rules must be a list", file=sys.stderr)
        return 1
    rule_types = [
        rule.get("type")
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("type"), str)
    ]
    required_types = {
        "required_signatures",
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    }
    if len(rule_types) != len(required_types) or set(rule_types) != required_types:
        print(
            f"{ruleset_path.relative_to(ROOT)}: rule types must appear exactly once: {sorted(required_types)}",
            file=sys.stderr,
        )
        ok = False
    by_type = {
        rule["type"]: rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") in required_types
    }

    pr_parameters = by_type.get("pull_request", {}).get("parameters", {})
    if pr_parameters.get("allowed_merge_methods") != ["merge"]:
        print(
            f"{ruleset_path.relative_to(ROOT)}: pull requests must preserve signed commits with merge-only integration",
            file=sys.stderr,
        )
        ok = False

    status_parameters = by_type.get("required_status_checks", {}).get("parameters", {})
    expected_checks = [
        {"context": "check", "integration_id": 15368},
        {"context": "changelog-gate", "integration_id": 15368},
    ]
    if status_parameters.get("required_status_checks") != expected_checks:
        print(
            f"{ruleset_path.relative_to(ROOT)}: checks must bind GitHub Actions app 15368",
            file=sys.stderr,
        )
        ok = False

    check_job = workflow.get("jobs", {}).get("check")
    check_steps = check_job.get("steps", []) if isinstance(check_job, dict) else []
    check_runs = [
        step.get("run")
        for step in check_steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    if (
        not isinstance(check_job, dict)
        or check_job.get("runs-on") != "tinyland-nix"
        or check_job.get("if")
        != "github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository"
        or "nix develop --command just check" not in check_runs
    ):
        print(
            f"{workflow_path.relative_to(ROOT)}: active check must be same-repo-only on tinyland-nix and run just check",
            file=sys.stderr,
        )
        ok = False
    validate_events = workflow_events(workflow)
    if (
        set(validate_events) != {"pull_request", "push"}
        or validate_events.get("pull_request") is not None
        or validate_events.get("push") != {"branches": ["main"]}
    ):
        print(
            f"{workflow_path.relative_to(ROOT)}: check producer must run on every PR and main push",
            file=sys.stderr,
        )
        ok = False
    if workflow.get("permissions") != {"contents": "read"}:
        print(
            f"{workflow_path.relative_to(ROOT)}: check producer must remain contents-read-only",
            file=sys.stderr,
        )
        ok = False
    if isinstance(check_job, dict) and check_job.get("permissions") is not None:
        print(
            f"{workflow_path.relative_to(ROOT)}: check job must inherit read-only workflow permissions",
            file=sys.stderr,
        )
        ok = False
    workflow_dir = ROOT / ".github" / "workflows"
    workflow_paths = sorted(
        set(workflow_dir.glob("*.yml")) | set(workflow_dir.glob("*.yaml"))
    )
    producers = {"check": [], "changelog-gate": []}
    for candidate_path in workflow_paths:
        try:
            candidate = load_workflow(candidate_path)
        except ValueError as error:
            print(error, file=sys.stderr)
            ok = False
            continue
        for job_id, job in candidate.get("jobs", {}).items():
            if not isinstance(job, dict):
                continue
            effective_context = job.get("name", job_id)
            if effective_context in producers:
                producers[effective_context].append(
                    candidate_path.relative_to(ROOT).as_posix()
                )
    expected_producers = {
        "check": [".github/workflows/validate.yml"],
        "changelog-gate": [".github/workflows/release.yml"],
    }
    for context, expected in expected_producers.items():
        if producers[context] != expected:
            print(
                f"required {context} context must have one workflow producer, "
                f"found {producers[context]}",
                file=sys.stderr,
            )
            ok = False
    checkout_steps = [
        step
        for step in check_steps
        if isinstance(step, dict) and step.get("uses") == "actions/checkout@v6"
    ]
    if (
        len(checkout_steps) != 1
        or checkout_steps[0].get("with", {}).get("persist-credentials") is not False
        or checkout_steps[0].get("with", {}).get("ref")
        != "${{ github.event.pull_request.head.sha || github.sha }}"
    ):
        print(
            f"{workflow_path.relative_to(ROOT)}: check checkout must use the exact head without persisted credentials",
            file=sys.stderr,
        )
        ok = False

    expected_actions_policy = {
        "repository": "tinyland-inc/ci-templates",
        "visibility": "public",
        "default_workflow_permissions": "read",
        "can_approve_pull_request_reviews": False,
        "fork_pr_approval_policy": "all_external_contributors",
        "self_hosted_pull_request_policy": "same-repository-only",
        "fork_handoff": "review-then-move-to-signed-same-repository-branch",
    }
    if actions_policy != expected_actions_policy:
        print(
            f"{actions_policy_path.relative_to(ROOT)}: public self-hosted runner policy drifted",
            file=sys.stderr,
        )
        ok = False

    gate_job = release.get("jobs", {}).get("changelog-gate")
    gate_steps = gate_job.get("steps", []) if isinstance(gate_job, dict) else []
    release_events = workflow_events(release)
    if (
        set(release_events) != {"pull_request", "push"}
        or release_events.get("pull_request") != {"branches": ["main"]}
        or release_events.get("push") != {"branches": ["main"]}
    ):
        print(
            f"{release_path.relative_to(ROOT)}: release workflow must run only for main pull requests and main pushes",
            file=sys.stderr,
        )
        ok = False
    if release.get("permissions") != {"contents": "read"}:
        print(
            f"{release_path.relative_to(ROOT)}: workflow permissions must default to contents read",
            file=sys.stderr,
        )
        ok = False
    gate_checkouts = [
        step
        for step in gate_steps
        if isinstance(step, dict) and step.get("uses") == "actions/checkout@v6"
    ]
    expected_gate_checkout = {
        "ref": "${{ github.event.pull_request.head.sha }}",
        "fetch-depth": 0,
        "persist-credentials": False,
    }
    if len(gate_checkouts) != 1 or gate_checkouts[0].get("with") != expected_gate_checkout:
        print(
            f"{release_path.relative_to(ROOT)}: changelog gate checkout must be exact-head and credential-free",
            file=sys.stderr,
        )
        ok = False
    tag_job = release.get("jobs", {}).get("tag-on-release-commit")
    if not isinstance(tag_job, dict) or tag_job.get("permissions") != {"contents": "write"}:
        print(
            f"{release_path.relative_to(ROOT)}: only the tag job may receive contents write",
            file=sys.stderr,
        )
        ok = False
    if gate_job.get("permissions") is not None:
        print(
            f"{release_path.relative_to(ROOT)}: changelog gate must inherit read-only workflow permissions",
            file=sys.stderr,
        )
        ok = False
    if tag_job.get("if") != "github.event_name == 'push' && github.ref == 'refs/heads/main'":
        print(
            f"{release_path.relative_to(ROOT)}: tag write authority must stay push-main-only",
            file=sys.stderr,
        )
        ok = False
    gate_runs = [
        step.get("run")
        for step in gate_steps
        if isinstance(step, dict)
        and step.get("name") == "Assert this PR amends ## [Unreleased]"
        and isinstance(step.get("run"), str)
    ]
    gate_script = gate_runs[0] if len(gate_runs) == 1 else ""
    for required in (
        'base="${{ github.event.pull_request.base.sha }}"',
        'head="${{ github.event.pull_request.head.sha }}"',
        'base_body=$(git show "$base:CHANGELOG.md" | extract_unreleased)',
        'if [ "$head_body" = "$base_body" ]; then',
    ):
        if required not in gate_script:
            print(
                f"{release_path.relative_to(ROOT)}: active changelog gate lacks: {required}",
                file=sys.stderr,
            )
            ok = False

    if not ok:
        return 1
    print("source contract guards remote checks and declares signed merge-only branch rails")
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
            "lane-status-namespace-contract",
            "default-branch-ruleset-contract",
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
    if args.check == "lane-status-namespace-contract":
        return check_lane_status_namespace_contract()
    if args.check == "default-branch-ruleset-contract":
        return check_default_branch_ruleset_contract()
    if args.check == "cache-backed-optin-contract":
        return check_cache_backed_optin_contract()
    return check_internal_refs()


if __name__ == "__main__":
    raise SystemExit(main())
