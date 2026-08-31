"""Static CT-01 contract for ci-templates' future self-validation lane."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WORKFLOW = Path(".github/workflows/validate.yml")
JUSTFILE = Path("Justfile")
EXPECTED_CHECK_TARGETS = (
    "yaml-parse",
    "json-parse",
    "vendored-schema-provenance-check",
    "repo-manifest-validate",
    "manifest-validate-selftest",
    "internal-refs-check",
    "js-bazel-runner-contract-check",
    "rust-bazel-application-contract-check",
    "flywheel-reapi-proof-contract-check",
    "restricted-workflow-contract-check",
    "runner-group-contract-selftest",
    "runner-group-contract-check",
    "repo-role-census-contract-selftest",
    "repo-role-census-contract-check",
    "endpoint-free-check",
    "ci-cached-endpoint-free-check",
    "cache-backed-optin-contract-check",
    "cache-contract-selftest",
    "secrets-scan-dir",
    "lint-runs-on-selftest",
    "lint-runs-on-check",
    "no-hosted-runners-selftest",
    "no-hosted-runners-check",
    "lanes-schema-runner-class-check",
    "gf-i09-publisher-contract-check",
    "gf-i09-publisher-contract-selftest",
)
CHECK_COMMAND = "run: nix develop --no-eval-cache --command just check"
ACTIONLINT_COMMAND = (
    "run: nix develop --no-eval-cache --command just actionlint-check"
)


def check_targets(source: str) -> tuple[str, ...]:
    match = re.search(r"(?m)^check: ([^\n]+)$", source)
    if not match:
        return ()
    return tuple(match.group(1).split())


def verdict(source: str) -> list[str]:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    header = source.split("\njobs:\n", 1)[0]
    require(
        re.search(
            r"(?m)^on:\n  pull_request:\n    branches: \[main\]\n"
            r"  push:\n    branches: \[main\]\n",
            header,
        )
        is not None,
        "validate must trigger on pull_request and push for main",
    )
    require(
        all(
            marker not in header
            for marker in ("pull_request_target:", "workflow_dispatch:", "schedule:")
        ),
        "validate may not add a privileged or manually invoked trigger",
    )
    permission_match = re.search(
        r"(?m)^permissions:\n((?:  [a-z-]+: [a-z]+\n)+)", header
    )
    require(
        permission_match is not None
        and permission_match.group(1) == "  contents: read\n",
        "validate permissions must be exactly read-only contents",
    )
    require(
        "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in header,
        "only pull-request validation may be cancel-in-progress",
    )
    require(
        source.count(CHECK_COMMAND) == 1,
        "validate must run the complete registered just check exactly once",
    )
    require(
        source.count(ACTIONLINT_COMMAND) == 1,
        "validate must run the Just-owned actionlint contract exactly once",
    )
    checkout_refs = re.findall(r"actions/checkout@([^\s#]+)", source)
    require(
        len(checkout_refs) == 1
        and re.fullmatch(r"[0-9a-f]{40}", checkout_refs[0]) is not None,
        "checkout must appear once at one immutable 40-hex action commit",
    )
    require(
        source.count("uses: ./.github/actions/nix-setup") == 1,
        "validate must dogfood the checked-in nix-setup action exactly once",
    )
    require(
        re.search(r"(?m)^    runs-on:", source) is not None,
        "validate must declare a runner; the ratified decision owns its value",
    )
    require("continue-on-error:" not in source, "validate may not fail soft")
    require("|| true" not in source, "validate may not suppress a failing command")
    require("${{ secrets." not in source, "validate may not consume a secret")
    return errors


def census_errors(just_source: str) -> list[str]:
    actual = check_targets(just_source)
    errors = []
    if actual != EXPECTED_CHECK_TARGETS:
        errors.append(
            "CT-01 check census changed: "
            f"expected {len(EXPECTED_CHECK_TARGETS)}, observed {len(actual)}"
        )
    if len(actual) < 15 or actual[14] != "endpoint-free-check":
        errors.append("endpoint-free-check must remain CT-01 target 15")
    return errors


def self_test() -> int:
    baseline = """name: validate
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: validate-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  validate:
    runs-on: runner-selection-owned-by-ratified-carrier
    steps:
      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567
      - uses: ./.github/actions/nix-setup
      - run: nix develop --no-eval-cache --command just check
      - run: nix develop --no-eval-cache --command just actionlint-check
"""
    initial = verdict(baseline)
    if initial:
        print("CT-01 self-test baseline invalid:", file=sys.stderr)
        for error in initial:
            print(f"- {error}", file=sys.stderr)
        return 1
    mutations = {
        "pull request trigger removed": baseline.replace(
            "  pull_request:\n    branches: [main]\n", "", 1
        ),
        "push trigger removed": baseline.replace(
            "  push:\n    branches: [main]\n", "", 1
        ),
        "privileged trigger": baseline.replace(
            "on:\n", "on:\n  pull_request_target:\n", 1
        ),
        "write permission": baseline.replace("contents: read", "contents: write", 1),
        "unconditional cancellation": baseline.replace(
            "${{ github.event_name == 'pull_request' }}", "true", 1
        ),
        "subset check": baseline.replace(
            "just check", "just endpoint-free-check", 1
        ),
        "direct actionlint": baseline.replace(
            "just actionlint-check", "actionlint", 1
        ),
        "mutable checkout": baseline.replace(
            "0123456789abcdef0123456789abcdef01234567", "main", 1
        ),
        "nix setup removed": baseline.replace(
            "uses: ./.github/actions/nix-setup", "run: true", 1
        ),
        "fail soft": baseline.replace(
            "run: nix develop --no-eval-cache --command just check",
            "continue-on-error: true\n"
            "      - run: nix develop --no-eval-cache --command just check",
            1,
        ),
    }
    failures = []
    for name, mutated in mutations.items():
        if mutated == baseline:
            failures.append(f"{name}: mutation did not alter source")
        elif not verdict(mutated):
            failures.append(f"{name}: checker accepted mutation")
    if failures:
        print("CT-01 mutation self-test FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"CT-01 mutation self-test passed ({len(mutations)} hostile cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not JUSTFILE.is_file():
        print(f"{JUSTFILE}: missing", file=sys.stderr)
        return 1
    errors = census_errors(JUSTFILE.read_text(encoding="utf-8"))
    if WORKFLOW.is_file():
        errors.extend(verdict(WORKFLOW.read_text(encoding="utf-8")))
    else:
        print(
            "CT-01 validation workflow absent: runner-group/fork-isolation decision HOLD"
        )
    if errors:
        for error in errors:
            print(f"CT-01 contract: {error}", file=sys.stderr)
        return 1
    print(
        "CT-01 static contract holds: 26 targets, endpoint-free-check is target 15"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
