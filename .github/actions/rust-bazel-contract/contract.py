#!/usr/bin/env python3
"""Fail-closed contract for the reusable native Rust+Bazel workflow."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


TARGET_RE = re.compile(
    r"^(?:@@?[A-Za-z0-9._+~-]+)?//[A-Za-z0-9._+~/\-]*:" r"[A-Za-z0-9._+~/=,\-]+$"
)
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
OS_MAP = {"darwin": "macOS", "linux": "Linux"}
ARCH_MAP = {"aarch64": "ARM64", "x86_64": "X64"}
BAZEL_PLATFORM_MAP = {
    ("darwin", "aarch64"): "//platforms:aarch64-apple-darwin",
    ("darwin", "x86_64"): "//platforms:x86_64-apple-darwin",
    ("linux", "aarch64"): "//platforms:aarch64-unknown-linux-gnu",
    ("linux", "x86_64"): "//platforms:x86_64-unknown-linux-gnu",
}
LANE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUNNER_GROUP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,54}-infra$")
ADMITTED_RUNNER_GROUPS = {"tinyland-infra"}
ORG_CAPABILITY_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]*-(?:nix|nix-heavy|nix-kvm|nix-gpu|docker|dind)$"
)
RUST_BAZEL_CAPABILITY_SUFFIXES = ("nix", "nix-heavy")
HOSTED_RUNNER_RE = re.compile(
    r"^(?:(?:ubuntu|macos|windows)-|(?:depot|warp|buildjet|blacksmith|namespace-profile)-)",
    re.IGNORECASE,
)
CANONICAL_PLATFORM_LABELS = {"Linux", "macOS", "X64", "ARM64"}
KNOWN_REPO_LABEL_FOSSILS = {
    "dollhouse-farm-nix",
    "chapel-nix",
    "jesssullivan-nix-heavy",
    "massageithaca-dind",
}
REF_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
ADMITTED_EVENTS = {
    "merge_group",
    "pull_request",
    "push",
    "schedule",
    "workflow_dispatch",
}
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
    target_name = label.rsplit(":", maxsplit=1)[-1]
    if (
        "..." in label
        or "*" in label
        or target_name in {"all", "all-targets"}
        or not TARGET_RE.fullmatch(label)
    ):
        raise ContractError(
            f"{name} must be an exact Bazel label with an explicit target; got {label!r}"
        )
    return label


def validate_targets(name: str, raw: str) -> list[str]:
    targets = json_string_array(name, raw, maximum=64)
    return [exact_bazel_label(name, target) for target in targets]


def strict_bool(name: str, raw: str) -> bool:
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ContractError(f"{name} must be true or false")


def bounded_integer(name: str, raw: str, minimum: int, maximum: int) -> int:
    if not raw.isdigit():
        raise ContractError(f"{name} must be an integer")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ContractError(f"{name} must be between {minimum} and {maximum}")
    return value


def validate_caller_admission(env: dict[str, str]) -> None:
    if not strict_bool("repository_private", env.get("REPOSITORY_PRIVATE", "")):
        raise ContractError(
            "private native runners require a private caller repository"
        )
    event_name = env.get("EVENT_NAME", "")
    if event_name not in ADMITTED_EVENTS:
        raise ContractError(f"caller event is not admitted: {event_name!r}")
    repository = env.get("REPOSITORY", "")
    if not REPOSITORY_RE.fullmatch(repository):
        raise ContractError("repository must be an exact owner/name")
    if event_name == "pull_request":
        head_repository = env.get("HEAD_REPOSITORY", "")
        if not REPOSITORY_RE.fullmatch(head_repository):
            raise ContractError(
                "pull-request head repository must be an exact owner/name"
            )
        if head_repository != repository:
            raise ContractError(
                "fork pull requests cannot receive private native runners"
            )


def validate_runner_group(raw: str) -> str:
    if not RUNNER_GROUP_RE.fullmatch(raw):
        raise ContractError(
            "runner_group must be an exact owner-overlay group ending in -infra"
        )
    if raw not in ADMITTED_RUNNER_GROUPS:
        raise ContractError(
            "runner_group is not in the reviewed private-group allowlist"
        )
    return raw


def validate_runner_labels(
    labels: list[str], runner_group: str, expected_os: str, expected_arch: str
) -> None:
    if any(
        label.strip() != label or any(char.isspace() for char in label)
        for label in labels
    ):
        raise ContractError("expected runner labels must not contain whitespace")
    for label in labels:
        if label == "self-hosted":
            raise ContractError("bare self-hosted is not an admitted capability label")
        if HOSTED_RUNNER_RE.match(label):
            raise ContractError(f"hosted runner label is not admitted: {label!r}")
        if label in KNOWN_REPO_LABEL_FOSSILS:
            raise ContractError(
                f"known repo-specific runner label is not admitted: {label!r}"
            )
        if label not in CANONICAL_PLATFORM_LABELS and not ORG_CAPABILITY_RE.fullmatch(
            label
        ):
            raise ContractError(
                "runner labels may contain only one org capability class plus "
                f"canonical OS/architecture labels; got {label!r}"
            )
    capability_labels = [
        label for label in labels if ORG_CAPABILITY_RE.fullmatch(label)
    ]
    if len(capability_labels) != 1:
        raise ContractError(
            "runner labels must contain exactly one org capability class"
        )
    owner_prefix = runner_group.removesuffix("-infra")
    admitted_capability_labels = {
        f"{owner_prefix}-{suffix}" for suffix in RUST_BAZEL_CAPABILITY_SUFFIXES
    }
    if capability_labels[0] not in admitted_capability_labels:
        raise ContractError(
            "runner capability label must be an exact owner-group capability, "
            "not a repo-shaped label"
        )
    expected_platform_labels = {OS_MAP[expected_os], ARCH_MAP[expected_arch]}
    actual_platform_labels = set(labels) & CANONICAL_PLATFORM_LABELS
    if actual_platform_labels != expected_platform_labels:
        raise ContractError(
            "runner labels must contain exactly the declared native OS and "
            f"architecture labels {sorted(expected_platform_labels)}"
        )


def validate_bazel_platform(label: str, expected_os: str, expected_arch: str) -> str:
    exact_bazel_label("bazel_platform", label)
    expected = BAZEL_PLATFORM_MAP[(expected_os, expected_arch)]
    if label != expected:
        raise ContractError(
            f"bazel_platform must be the canonical native label {expected!r}; got {label!r}"
        )
    return label


def validate_matrix_contract(env: dict[str, str]) -> dict[str, str]:
    validate_caller_admission(env)
    bounded_integer("timeout_minutes", env.get("TIMEOUT_MINUTES", ""), 5, 180)
    bounded_integer("max_parallel", env.get("MAX_PARALLEL", ""), 1, 4)
    runner_group = validate_runner_group(env.get("RUNNER_GROUP", ""))
    raw = env.get("PLATFORM_MATRIX_JSON", "")
    if len(raw.encode("utf-8")) > 65_536:
        raise ContractError("platform_matrix_json exceeds the 64 KiB input limit")
    try:
        lanes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(f"platform_matrix_json must be valid JSON: {exc}") from exc
    if not isinstance(lanes, list) or not lanes:
        raise ContractError("platform_matrix_json must be a non-empty JSON array")
    if len(lanes) > 4:
        raise ContractError(
            "platform_matrix_json may contain at most four native lanes"
        )

    expected_keys = {"name", "os", "arch", "runner_labels", "bazel_platform"}
    canonical_lanes: list[dict[str, object]] = []
    seen_names: set[str] = set()
    seen_platforms: set[tuple[str, str]] = set()
    for index, lane in enumerate(lanes):
        if not isinstance(lane, dict) or set(lane) != expected_keys:
            raise ContractError(
                f"platform_matrix_json lane {index} must contain exactly {sorted(expected_keys)}"
            )
        lane_name = lane["name"]
        expected_os = lane["os"]
        expected_arch = lane["arch"]
        labels = lane["runner_labels"]
        bazel_platform = lane["bazel_platform"]
        if not isinstance(lane_name, str) or not LANE_NAME_RE.fullmatch(lane_name):
            raise ContractError(
                f"platform_matrix_json lane {index} has an invalid name"
            )
        if lane_name in seen_names:
            raise ContractError(
                f"platform_matrix_json duplicates lane name {lane_name!r}"
            )
        if (
            not isinstance(expected_os, str)
            or expected_os not in OS_MAP
            or not isinstance(expected_arch, str)
            or expected_arch not in ARCH_MAP
        ):
            raise ContractError(
                f"platform_matrix_json lane {lane_name!r} has an unsupported native platform"
            )
        platform_key = (expected_os, expected_arch)
        if platform_key in seen_platforms:
            raise ContractError(
                f"platform_matrix_json duplicates native platform {expected_os}/{expected_arch}"
            )
        if (
            not isinstance(labels, list)
            or not labels
            or len(labels) > 16
            or not all(isinstance(label, str) and label for label in labels)
            or len(set(labels)) != len(labels)
        ):
            raise ContractError(
                f"platform_matrix_json lane {lane_name!r} has invalid runner_labels"
            )
        if not isinstance(bazel_platform, str):
            raise ContractError(
                f"platform_matrix_json lane {lane_name!r} has invalid bazel_platform"
            )
        validate_runner_labels(labels, runner_group, expected_os, expected_arch)
        validate_bazel_platform(bazel_platform, expected_os, expected_arch)
        seen_names.add(lane_name)
        seen_platforms.add(platform_key)
        canonical_lanes.append(
            {
                "name": lane_name,
                "os": expected_os,
                "arch": expected_arch,
                "runner_labels": labels,
                "bazel_platform": bazel_platform,
            }
        )

    for _output_name, env_name in TARGET_INPUTS:
        validate_targets(env_name.lower(), env.get(env_name, ""))
    return {
        "platform_matrix_json": json.dumps(
            canonical_lanes, separators=(",", ":"), sort_keys=True
        )
    }


def cache_upload_allowed(env: dict[str, str]) -> bool:
    cache_enabled = strict_bool("cache_enabled", env.get("CACHE_ENABLED", ""))
    upload_requested = strict_bool(
        "trusted_cache_upload", env.get("TRUSTED_CACHE_UPLOAD", "")
    )
    ref_protected = strict_bool("ref_protected", env.get("REF_PROTECTED", ""))
    protected_branch = env.get("PROTECTED_BRANCH", "")
    release_tag_prefix = env.get("RELEASE_TAG_PREFIX", "")
    for name, value, allow_empty in (
        ("protected_branch", protected_branch, False),
        ("release_tag_prefix", release_tag_prefix, True),
    ):
        if (not value and not allow_empty) or (
            value
            and (
                not REF_COMPONENT_RE.fullmatch(value) or ".." in value or "//" in value
            )
        ):
            raise ContractError(f"{name} is not a safe exact ref component")

    ref_name = env.get("REF_NAME", "")
    trusted_ref = ref_name == f"refs/heads/{protected_branch}" or bool(
        release_tag_prefix and ref_name.startswith(f"refs/tags/{release_tag_prefix}")
    )
    return all(
        (
            cache_enabled,
            upload_requested,
            env.get("EVENT_NAME", "") == "push",
            ref_protected,
            trusted_ref,
        )
    )


def validate_cache_authority(env: dict[str, str], upload_allowed: bool) -> None:
    if env.get("CACHE_SUBSTRATE_MODE", "") != "shared-cache-backed":
        raise ContractError(
            "cache_substrate_mode must be shared-cache-backed; remote execution is not admitted"
        )
    enabled = strict_bool("cache_enabled", env.get("CACHE_ENABLED", ""))
    endpoint = env.get("CACHE_ENDPOINT", "")
    read_header_present = strict_bool(
        "cache_read_header_present", env.get("CACHE_READ_HEADER_PRESENT", "")
    )
    write_header_present = strict_bool(
        "cache_write_header_present", env.get("CACHE_WRITE_HEADER_PRESENT", "")
    )
    headers_distinct = strict_bool(
        "cache_headers_distinct", env.get("CACHE_HEADERS_DISTINCT", "")
    )
    if not enabled:
        if endpoint:
            raise ContractError("disabled cache must not materialize an endpoint")
        return
    if not endpoint:
        raise ContractError("enabled cache requires a runtime endpoint")
    if any(char.isspace() or ord(char) < 32 for char in endpoint):
        raise ContractError(
            "cache endpoint must not contain whitespace or control bytes"
        )
    parsed = urlsplit(endpoint)
    if parsed.username is not None or parsed.password is not None:
        raise ContractError("cache endpoint must not embed userinfo credentials")
    if parsed.query or parsed.fragment:
        raise ContractError(
            "cache endpoint must not embed query or fragment credentials"
        )
    if not read_header_present:
        raise ContractError("enabled cache requires a distinct read-only header secret")
    if not headers_distinct:
        raise ContractError("cache read and write header secrets must be distinct")
    if upload_allowed and not write_header_present:
        raise ContractError(
            "admitted cache upload requires a distinct write header secret"
        )


def require_tracked(workspace: Path, path: str) -> None:
    candidate = workspace / path
    if candidate.is_symlink():
        raise ContractError(
            f"required workspace file must be a regular tracked file, not a symlink: {path}"
        )
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


def validate_workspace(workspace: Path, required_major: str) -> str:
    if not required_major.isdigit() or int(required_major) < 1:
        raise ContractError("required_bazel_major must be a positive integer")
    for path in (".bazelversion", "MODULE.bazel", "MODULE.bazel.lock"):
        require_tracked(workspace, path)
    if (workspace / ".bazeliskrc").exists():
        raise ContractError(
            "workspace .bazeliskrc is not admitted in authoritative CI; use tracked Bazel graph inputs"
        )
    version = (workspace / ".bazelversion").read_text(encoding="utf-8").strip()
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise ContractError(".bazelversion must contain one exact stable x.y.z version")
    if match.group(1) != required_major:
        raise ContractError(
            f".bazelversion pins Bazel {version}, expected major {required_major}"
        )
    return version


def validate_contract(env: dict[str, str], workspace: Path) -> dict[str, str]:
    runner_group = validate_runner_group(env.get("RUNNER_GROUP", ""))
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
    validate_runner_labels(expected_labels, runner_group, expected_os, expected_arch)

    validate_bazel_platform(env.get("BAZEL_PLATFORM", ""), expected_os, expected_arch)
    bazel_version = validate_workspace(workspace, env.get("REQUIRED_BAZEL_MAJOR", "9"))

    outputs: dict[str, str] = {}
    for output_name, env_name in TARGET_INPUTS:
        outputs[output_name] = " ".join(
            validate_targets(env_name.lower(), env.get(env_name, ""))
        )
    upload_allowed = cache_upload_allowed(env)
    validate_cache_authority(env, upload_allowed)
    outputs["cache_upload"] = "true" if upload_allowed else "false"
    outputs["bazel_version"] = bazel_version
    return outputs


def write_outputs(path: Path, outputs: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def self_test() -> int:
    def expect_contract_error(label: str, operation: Callable[[], object]) -> None:
        try:
            operation()
        except ContractError:
            return
        raise AssertionError(f"accepted invalid {label}")

    assert exact_bazel_label("target", "//crates/core:unit_test")
    assert exact_bazel_label("target", "@rules_rust//rust:toolchain")
    for invalid in (
        "//...",
        "//crates/core",
        "//crates/core:all",
        "//crates/core:all-targets",
        "//x:y;echo",
        "-//x:y",
        "",
    ):
        expect_contract_error(
            f"label {invalid!r}",
            lambda invalid=invalid: exact_bazel_label("target", invalid),
        )
    expect_contract_error(
        "empty target array", lambda: json_string_array("targets", "[]", maximum=64)
    )
    validate_runner_labels(
        ["tinyland-nix", "macOS", "ARM64"],
        "tinyland-infra",
        "darwin",
        "aarch64",
    )
    for invalid_labels in (
        ["ubuntu-latest"],
        ["self-hosted"],
        ["dollhouse-farm-nix"],
        ["macOS", "ARM64"],
        ["tinyland-nix", "tinyland-docker"],
        ["tinyland-nix-darwin-aarch64"],
        ["tinyland-prompt-pulse-nix", "macOS", "ARM64"],
    ):
        expect_contract_error(
            f"runner labels {invalid_labels!r}",
            lambda invalid_labels=invalid_labels: validate_runner_labels(
                invalid_labels, "tinyland-infra", "darwin", "aarch64"
            ),
        )
    expect_contract_error(
        "cross-owner runner label",
        lambda: validate_runner_labels(
            ["anotherorg-nix", "macOS", "ARM64"],
            "tinyland-infra",
            "darwin",
            "aarch64",
        ),
    )
    expect_contract_error(
        "repo-shaped matching group and label",
        lambda: (
            validate_runner_group("tinyland-prompt-pulse-infra"),
            validate_runner_labels(
                ["tinyland-prompt-pulse-nix", "macOS", "ARM64"],
                "tinyland-prompt-pulse-infra",
                "darwin",
                "aarch64",
            ),
        ),
    )
    expect_contract_error(
        "mismatched native runner labels",
        lambda: validate_runner_labels(
            ["tinyland-nix", "Linux", "X64"],
            "tinyland-infra",
            "darwin",
            "aarch64",
        ),
    )

    valid_lane = {
        "name": "darwin-aarch64",
        "os": "darwin",
        "arch": "aarch64",
        "runner_labels": ["tinyland-nix", "macOS", "ARM64"],
        "bazel_platform": "//platforms:aarch64-apple-darwin",
    }
    preflight_env = {
        "REPOSITORY_PRIVATE": "true",
        "EVENT_NAME": "pull_request",
        "REPOSITORY": "tinyland-inc/prompt-pulse",
        "HEAD_REPOSITORY": "tinyland-inc/prompt-pulse",
        "TIMEOUT_MINUTES": "60",
        "MAX_PARALLEL": "2",
        "RUNNER_GROUP": "tinyland-infra",
        "PLATFORM_MATRIX_JSON": json.dumps([valid_lane]),
    }
    for _output_name, env_name in TARGET_INPUTS:
        preflight_env[env_name] = '["//contract:target"]'
    preflight_outputs = validate_matrix_contract(preflight_env)
    assert json.loads(preflight_outputs["platform_matrix_json"]) == [valid_lane]
    for name, override in (
        ("public repository", {"REPOSITORY_PRIVATE": "false"}),
        ("pull request target", {"EVENT_NAME": "pull_request_target"}),
        ("fork pull request", {"HEAD_REPOSITORY": "untrusted/fork"}),
        ("unknown event", {"EVENT_NAME": "issue_comment"}),
        ("unbounded timeout", {"TIMEOUT_MINUTES": "1440"}),
        ("fractional concurrency", {"MAX_PARALLEL": "1.5"}),
    ):
        expect_contract_error(
            name,
            lambda override=override: validate_matrix_contract(
                {**preflight_env, **override}
            ),
        )
    for name, matrix in (
        ("empty matrix", []),
        ("duplicate lane", [valid_lane, valid_lane]),
        ("unexpected lane field", [{**valid_lane, "extra": True}]),
        (
            "hosted matrix lane",
            [{**valid_lane, "runner_labels": ["ubuntu-latest"]}],
        ),
        (
            "recursive platform target",
            [{**valid_lane, "bazel_platform": "//platforms:all"}],
        ),
        (
            "mismatched native labels",
            [{**valid_lane, "runner_labels": ["tinyland-nix", "Linux", "X64"]}],
        ),
        (
            "mismatched canonical platform",
            [
                {
                    **valid_lane,
                    "bazel_platform": "//platforms:x86_64-unknown-linux-gnu",
                }
            ],
        ),
    ):
        expect_contract_error(
            name,
            lambda matrix=matrix: validate_matrix_contract(
                {**preflight_env, "PLATFORM_MATRIX_JSON": json.dumps(matrix)}
            ),
        )

    base_cache_env = {
        "CACHE_ENABLED": "true",
        "CACHE_SUBSTRATE_MODE": "shared-cache-backed",
        "CACHE_ENDPOINT": "https://cache.example.invalid/cache",
        "CACHE_READ_HEADER_PRESENT": "true",
        "CACHE_WRITE_HEADER_PRESENT": "true",
        "CACHE_HEADERS_DISTINCT": "true",
        "TRUSTED_CACHE_UPLOAD": "true",
        "EVENT_NAME": "push",
        "REF_NAME": "refs/heads/main",
        "REF_PROTECTED": "true",
        "PROTECTED_BRANCH": "main",
        "RELEASE_TAG_PREFIX": "v",
    }
    assert cache_upload_allowed(base_cache_env)
    assert cache_upload_allowed({**base_cache_env, "REF_NAME": "refs/tags/v3.0.0-rc.1"})
    for override in (
        {"CACHE_ENABLED": "false"},
        {"TRUSTED_CACHE_UPLOAD": "false"},
        {"EVENT_NAME": "pull_request"},
        {"EVENT_NAME": "pull_request_target"},
        {"REF_PROTECTED": "false"},
        {"REF_NAME": "refs/heads/feature"},
        {"REF_NAME": "refs/tags/not-a-release"},
    ):
        assert not cache_upload_allowed({**base_cache_env, **override})
    expect_contract_error(
        "cache boolean",
        lambda: cache_upload_allowed({**base_cache_env, "CACHE_ENABLED": "1"}),
    )
    for name, override in (
        (
            "cache endpoint userinfo",
            {"CACHE_ENDPOINT": "https://writer:token@cache.example.invalid/cache"},
        ),
        (
            "cache endpoint query credential",
            {"CACHE_ENDPOINT": "https://cache.example.invalid/cache?token=writer"},
        ),
        ("missing read header", {"CACHE_READ_HEADER_PRESENT": "false"}),
        ("missing write header", {"CACHE_WRITE_HEADER_PRESENT": "false"}),
        ("identical cache headers", {"CACHE_HEADERS_DISTINCT": "false"}),
        ("executor substrate", {"CACHE_SUBSTRATE_MODE": "executor-backed"}),
    ):
        expect_contract_error(
            name,
            lambda override=override: validate_cache_authority(
                {**base_cache_env, **override}, True
            ),
        )
    validate_cache_authority(
        {
            **base_cache_env,
            "CACHE_ENABLED": "false",
            "CACHE_ENDPOINT": "",
            "CACHE_READ_HEADER_PRESENT": "false",
            "CACHE_WRITE_HEADER_PRESENT": "false",
            "CACHE_HEADERS_DISTINCT": "false",
        },
        False,
    )
    expect_contract_error(
        "protected branch",
        lambda: cache_upload_allowed({**base_cache_env, "PROTECTED_BRANCH": "../main"}),
    )

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
            "RUNNER_GROUP": "tinyland-infra",
            "LANE_NAME": "darwin-aarch64",
            "EXPECTED_OS": "darwin",
            "EXPECTED_ARCH": "aarch64",
            "ACTUAL_OS": "macOS",
            "ACTUAL_ARCH": "ARM64",
            "EXPECTED_RUNNER_LABELS_JSON": '["tinyland-nix","macOS","ARM64"]',
            "BAZEL_PLATFORM": "//platforms:aarch64-apple-darwin",
            "REQUIRED_BAZEL_MAJOR": "9",
            **base_cache_env,
        }
        for _output_name, env_name in TARGET_INPUTS:
            valid_env[env_name] = '["//contract:target"]'
        outputs = validate_contract(valid_env, workspace)
        assert outputs["build_targets"] == "//contract:target"
        assert outputs["cache_upload"] == "true"
        assert outputs["bazel_version"] == "9.2.0"

        for required_path in (".bazelversion", "MODULE.bazel", "MODULE.bazel.lock"):
            candidate = workspace / required_path
            original = candidate.read_bytes()
            symlink_target = workspace / f"untracked-{candidate.name}"
            symlink_target.write_bytes(original)
            candidate.unlink()
            candidate.symlink_to(symlink_target.name)
            subprocess.run(
                ["git", "add", "--", required_path], cwd=workspace, check=True
            )
            expect_contract_error(
                f"tracked symlink {required_path}",
                lambda: validate_contract(valid_env, workspace),
            )
            candidate.unlink()
            candidate.write_bytes(original)
            symlink_target.unlink()
            subprocess.run(
                ["git", "add", "--", required_path], cwd=workspace, check=True
            )

        (workspace / ".bazeliskrc").write_text(
            "USE_BAZEL_VERSION=latest\n", encoding="utf-8"
        )
        expect_contract_error(
            "workspace Bazelisk config",
            lambda: validate_contract(valid_env, workspace),
        )
        (workspace / ".bazeliskrc").unlink()

        for name, override in (
            ("runner group", {"RUNNER_GROUP": "tinyland"}),
            ("native OS", {"ACTUAL_OS": "Linux"}),
            ("native architecture", {"ACTUAL_ARCH": "X64"}),
            ("Bazel major", {"REQUIRED_BAZEL_MAJOR": "8"}),
        ):
            expect_contract_error(
                name,
                lambda override=override: validate_contract(
                    {**valid_env, **override}, workspace
                ),
            )

        output = workspace / "output"
        write_outputs(output, {"targets": "//a:b //c:d"})
        assert output.read_text(encoding="utf-8") == "targets=//a:b //c:d\n"

    driver = Path(__file__).with_name("bazelisk-ci")
    if not driver.is_file() or not os.access(driver, os.X_OK):
        raise AssertionError("release-vendored Bazelisk driver is not executable")
    with tempfile.TemporaryDirectory() as directory:
        driver_test = Path(directory)
        bin_dir = driver_test / "bin"
        bin_dir.mkdir()
        record = driver_test / "record"
        fake_bazelisk = bin_dir / "bazelisk"
        fake_bazelisk.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'base=%s\\n\' "${BAZELISK_BASE_URL-unset}" > "$RECORD"\n'
            'printf \'format=%s\\n\' "${BAZELISK_FORMAT_URL-unset}" >> "$RECORD"\n'
            'printf \'os_home=%s\\n\' "${BAZELISK_HOME_DARWIN-unset}" >> "$RECORD"\n'
            'printf \'home=%s\\n\' "$HOME" >> "$RECORD"\n'
            'printf \'bazelisk_home=%s\\n\' "$BAZELISK_HOME" >> "$RECORD"\n'
            'printf \'skip=%s\\n\' "$BAZELISK_SKIP_WRAPPER" >> "$RECORD"\n'
            'printf \'version=%s\\n\' "$USE_BAZEL_VERSION" >> "$RECORD"\n'
            'printf \'args=%s\\n\' "$*" >> "$RECORD"\n',
            encoding="utf-8",
        )
        fake_bazelisk.chmod(0o700)
        ci_home = driver_test / "ci-home"
        driver_env = {
            **os.environ,
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RECORD": str(record),
            "CI_BAZEL_VERSION": "9.2.0",
            "CI_BAZEL_HOME": str(ci_home),
            "BAZELISK_BASE_URL": "https://evil.invalid",
            "BAZELISK_FORMAT_URL": "https://evil.invalid/%v",
            "BAZELISK_HOME_DARWIN": str(driver_test / "poison"),
            "USE_BAZEL_VERSION": "latest",
        }
        subprocess.run(
            [str(driver), "build", "//contract:target"],
            env=driver_env,
            check=True,
        )
        assert record.read_text(encoding="utf-8") == (
            "base=unset\n"
            "format=unset\n"
            "os_home=unset\n"
            f"home={ci_home}/home\n"
            f"bazelisk_home={ci_home}/bazelisk\n"
            "skip=1\n"
            "version=9.2.0\n"
            "args=--ignore_all_rc_files build //contract:target\n"
        )
    print("rust-bazel application contract self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--matrix-preflight", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.matrix_preflight:
        if args.github_output is None:
            parser.error("--github-output is required with --matrix-preflight")
        try:
            write_outputs(
                args.github_output, validate_matrix_contract(dict(os.environ))
            )
        except ContractError as exc:
            print(f"rust-bazel matrix contract error: {exc}", file=sys.stderr)
            return 1
        print("native Rust+Bazel matrix contract validated")
        return 0
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
