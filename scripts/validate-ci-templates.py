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
        "must include a Tinyland capability-class label",
        '"tinyland-nix"',
        '"tinyland-docker"',
        '"tinyland-dind"',
        "runner_mode=shared requires shared_runner_labels_json",
    ]
    required_docs_snippets = [
        "`repo_owned` is a trust and registration boundary",
        "workflow-facing labels still stay shared Tinyland capability classes",
        "It must not resolve to a repo-shaped label.",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("check", choices=["manifest", "internal-refs", "js-bazel-runner-contract"])
    args = parser.parse_args()

    if args.check == "manifest":
        return validate_manifest()
    if args.check == "js-bazel-runner-contract":
        return check_js_bazel_package_runner_contract()
    return check_internal_refs()


if __name__ == "__main__":
    raise SystemExit(main())
