#!/usr/bin/env python3
"""Fail-closed contract for the reusable native Rust+Bazel workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


TARGET_RE = re.compile(
    r"^(?:@@?[A-Za-z0-9._+~-]+)?//[A-Za-z0-9._+~/\-]*:" r"[A-Za-z0-9._+~/=,\-]+$"
)
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
OS_MAP = {"darwin": "macOS", "linux": "Linux"}
ARCH_MAP = {"aarch64": "ARM64", "x86_64": "X64"}
LANE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TARGET_INPUTS = (
    ("rustfmt_targets", "RUSTFMT_TARGETS_JSON"),
    ("clippy_targets", "CLIPPY_TARGETS_JSON"),
    ("build_targets", "BUILD_TARGETS_JSON"),
    ("unit_test_targets", "UNIT_TEST_TARGETS_JSON"),
    ("integration_test_targets", "INTEGRATION_TEST_TARGETS_JSON"),
    ("package_targets", "PACKAGE_TARGETS_JSON"),
)


class ContractError(ValueError):
    """An operator-supplied workflow contract is invalid."""


def json_string_array(name: str, raw: str, *, maximum: int) -> list[str]:
    if len(raw.encode("utf-8")) > 16_384:
        raise ContractError(f"{name} exceeds the 16 KiB input limit")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{name} must be valid JSON: {exc}") from exc
    if not isinstance(value, list) or not value:
        raise ContractError(f"{name} must be a non-empty JSON array")
    if len(value) > maximum:
        raise ContractError(f"{name} may contain at most {maximum} entries")
    if not all(isinstance(item, str) and item for item in value):
        raise ContractError(f"{name} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ContractError(f"{name} contains duplicate entries")
    return value


def exact_bazel_label(name: str, label: str) -> str:
    if "..." in label or "*" in label or not TARGET_RE.fullmatch(label):
        raise ContractError(
            f"{name} must be an exact Bazel label with an explicit target; got {label!r}"
        )
    return label


def validate_targets(name: str, raw: str) -> list[str]:
    targets = json_string_array(name, raw, maximum=64)
    return [exact_bazel_label(name, target) for target in targets]


def require_tracked(workspace: Path, path: str) -> None:
    candidate = workspace / path
    if not candidate.is_file():
        raise ContractError(f"required workspace file is missing: {path}")
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise ContractError(f"required workspace file is not tracked: {path}")


def validate_workspace(workspace: Path, required_major: str) -> None:
    if not required_major.isdigit() or int(required_major) < 1:
        raise ContractError("required_bazel_major must be a positive integer")
    for path in (".bazelversion", "MODULE.bazel", "MODULE.bazel.lock"):
        require_tracked(workspace, path)
    version = (workspace / ".bazelversion").read_text(encoding="utf-8").strip()
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ContractError(".bazelversion must contain one exact stable x.y.z version")
    if match.group(1) != required_major:
        raise ContractError(
            f".bazelversion pins Bazel {version}, expected major {required_major}"
        )


def validate_contract(env: dict[str, str], workspace: Path) -> dict[str, str]:
    lane_name = env.get("LANE_NAME", "")
    if not LANE_NAME_RE.fullmatch(lane_name):
        raise ContractError(
            "lane_name must be 1-64 characters using letters, digits, dot, underscore, or hyphen"
        )
    expected_os = env.get("EXPECTED_OS", "")
    expected_arch = env.get("EXPECTED_ARCH", "")
    if expected_os not in OS_MAP:
        raise ContractError("expected_os must be darwin or linux")
    if expected_arch not in ARCH_MAP:
        raise ContractError("expected_arch must be aarch64 or x86_64")
    if env.get("ACTUAL_OS", "") != OS_MAP[expected_os]:
        raise ContractError(
            f"native OS mismatch: requested {expected_os}, runner reported {env.get('ACTUAL_OS', '')!r}"
        )
    if env.get("ACTUAL_ARCH", "") != ARCH_MAP[expected_arch]:
        raise ContractError(
            f"native architecture mismatch: requested {expected_arch}, runner reported {env.get('ACTUAL_ARCH', '')!r}"
        )

    expected_labels = json_string_array(
        "expected_runner_labels_json",
        env.get("EXPECTED_RUNNER_LABELS_JSON", ""),
        maximum=16,
    )
    if any(
        label.strip() != label or any(char.isspace() for char in label)
        for label in expected_labels
    ):
        raise ContractError("expected runner labels must not contain whitespace")

    exact_bazel_label("bazel_platform", env.get("BAZEL_PLATFORM", ""))
    validate_workspace(workspace, env.get("REQUIRED_BAZEL_MAJOR", "9"))

    outputs: dict[str, str] = {}
    for output_name, env_name in TARGET_INPUTS:
        outputs[output_name] = " ".join(
            validate_targets(env_name.lower(), env.get(env_name, ""))
        )
    return outputs


def write_outputs(path: Path, outputs: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def self_test() -> int:
    assert exact_bazel_label("target", "//crates/core:unit_test")
    assert exact_bazel_label("target", "@rules_rust//rust:toolchain")
    for invalid in ("//...", "//crates/core", "//x:y;echo", "-//x:y", ""):
        try:
            exact_bazel_label("target", invalid)
        except ContractError:
            pass
        else:
            raise AssertionError(f"accepted invalid label: {invalid!r}")
    try:
        json_string_array("targets", "[]", maximum=64)
    except ContractError:
        pass
    else:
        raise AssertionError("accepted an empty target array")
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
        (workspace / ".bazelversion").write_text("9.2.0\n", encoding="utf-8")
        (workspace / "MODULE.bazel").write_text(
            'module(name = "contract_test")\n', encoding="utf-8"
        )
        (workspace / "MODULE.bazel.lock").write_text("{}\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", ".bazelversion", "MODULE.bazel", "MODULE.bazel.lock"],
            cwd=workspace,
            check=True,
        )
        valid_env = {
            "LANE_NAME": "darwin-aarch64",
            "EXPECTED_OS": "darwin",
            "EXPECTED_ARCH": "aarch64",
            "ACTUAL_OS": "macOS",
            "ACTUAL_ARCH": "ARM64",
            "EXPECTED_RUNNER_LABELS_JSON": '["tinyland-nix-darwin-aarch64"]',
            "BAZEL_PLATFORM": "//platforms:aarch64-apple-darwin",
            "REQUIRED_BAZEL_MAJOR": "9",
        }
        for _output_name, env_name in TARGET_INPUTS:
            valid_env[env_name] = '["//contract:target"]'
        outputs = validate_contract(valid_env, workspace)
        assert outputs["build_targets"] == "//contract:target"

        output = workspace / "output"
        write_outputs(output, {"targets": "//a:b //c:d"})
        assert output.read_text(encoding="utf-8") == "targets=//a:b //c:d\n"
    print("rust-bazel application contract self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.workspace is None or args.github_output is None:
        parser.error("--workspace and --github-output are required")
    try:
        outputs = validate_contract(dict(os.environ), args.workspace.resolve())
        write_outputs(args.github_output, outputs)
    except ContractError as exc:
        print(f"rust-bazel contract error: {exc}", file=sys.stderr)
        return 1
    print("native Rust+Bazel target contract validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
