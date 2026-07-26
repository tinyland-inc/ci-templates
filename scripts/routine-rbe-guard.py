#!/usr/bin/env python3
"""Fail-closed TIN-2851 source, publication, and RBE evidence guard."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import tokenize
from typing import Any, Iterable


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CANONICAL_REPOSITORY = "tinyland-inc/ci-templates"
CANONICAL_REMOTE = "https://github.com/tinyland-inc/ci-templates.git"
CANONICAL_WORKFLOW = ".github/workflows/spoke-ci.yml"
CANONICAL_ACTION = ".github/actions/routine-rbe/action.yml"
ROUTINE_RBE_RELEASE_TAG = "v2.12.0"
CONTRACT_MARKER = "TIN-2851-routine-rbe-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SEMVER_V2_RE = re.compile(r"^v2\.[0-9]+\.[0-9]+$")
TARGET_RE = re.compile(
    r"^//(?:[A-Za-z0-9_./+-]+)?:[A-Za-z0-9_./+@=-]+$"
)
RUNNER_CLASS_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]*-(?:nix|nix-heavy|nix-kvm|nix-gpu|docker|dind)$"
)

SUPPORTED_CLASSES: dict[str, str] = {
    "sveltekit-app-build": "build",
    "sveltekit-unit-tests": "test",
    "deployment-bundle-packaging": "build",
    "docs-site-static-build": "build",
}

HASHED_HELPERS = (
    "scripts/routine-rbe-run.sh",
    "scripts/routine-rbe-guard.py",
    "config/routine-rbe-toolchain.json",
)

AUDITED_RELEASE_FILES = (
    *HASHED_HELPERS,
    CANONICAL_ACTION,
    CANONICAL_WORKFLOW,
)

BAZEL_SOURCE_NAMES = {
    ".bazelrc",
    ".bazelignore",
    ".bazeliskrc",
    ".bazelversion",
    "BUILD",
    "BUILD.bazel",
    "MODULE.bazel",
    "MODULE.bazel.lock",
    "REPO.bazel",
    "VENDOR.bazel",
    "WORKSPACE",
    "WORKSPACE.bazel",
}

FORBIDDEN_SOURCE_PATTERNS = (
    (re.compile(r"\blocal_path_override\s*\("), "local_path_override"),
    (re.compile(r"\bnew_local_repository\s*\("), "new_local_repository"),
    (re.compile(r"\blocal_repository\s*\("), "local_repository"),
    (re.compile(r"--(?:override|inject)_repository(?:=|\s)"), "local repository injection flag"),
    (re.compile(r"--package_path(?:=|\s)"), "ambient package path flag"),
    (re.compile(r"--(?:remote_executor|remote_cache)(?:=|\s)\S*"), "source-owned remote endpoint"),
    (re.compile(r"--(?:remote|remote_cache|remote_exec)_header(?:=|\s)"), "source-owned remote credential header"),
    (re.compile(r"--credential_helper(?:=|\s)"), "source-owned credential helper"),
    (re.compile(r"--spawn_strategy=local\b"), "local spawn strategy"),
    (re.compile(r"--strategy=[^\s=]+=local\b"), "local mnemonic strategy"),
)

ACTION_HASH_RE = re.compile(
    r"ROUTINE_RBE_(RUN|GUARD|TOOLCHAIN)_SHA256:\s*([0-9a-f]{64})"
)

ATTESTATION_METADATA_KEYS = {
    "contract": "TIN2851_CONTRACT",
    "action_repository": "TIN2851_ACTION_REPOSITORY",
    "action_ref": "TIN2851_ACTION_REF",
    "workflow_repository": "TIN2851_WORKFLOW_REPOSITORY",
    "workflow_file_path": "TIN2851_WORKFLOW_FILE_PATH",
    "workflow_ref": "TIN2851_WORKFLOW_REF",
    "workflow_sha": "TIN2851_WORKFLOW_SHA",
    "release_digest": "TIN2851_RELEASE_DIGEST",
    "workspace_digest": "TIN2851_WORKSPACE_DIGEST",
    "audited_workspace_digest": "TIN2851_AUDITED_WORKSPACE_DIGEST",
    "lane": "TIN2851_LANE",
    "target_class": "TIN2851_TARGET_CLASS",
    "target": "TIN2851_TARGET",
    "bazel_command": "TIN2851_BAZEL_COMMAND",
}


class GuardError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise GuardError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            fail(f"not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in stable_fields):
            fail(f"file mutated while hashing: {path}")
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def read_stable_bytes(path: pathlib.Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            fail(f"not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read()
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in stable_fields):
            fail(f"file mutated while reading: {path}")
    finally:
        os.close(descriptor)
    return data


def read_stable_text(path: pathlib.Path) -> str:
    try:
        return read_stable_bytes(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"cannot decode UTF-8 text from {path}: {exc}")


def read_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(read_stable_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {path}: {exc}")


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def require_within(root: pathlib.Path, candidate: pathlib.Path, description: str) -> pathlib.Path:
    root = root.resolve()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        fail(f"{description} is unavailable: {candidate}: {exc}")
    try:
        resolved.relative_to(root)
    except ValueError:
        fail(f"{description} escapes the workspace: {candidate} -> {resolved}")
    return resolved


def is_bazel_source(path: pathlib.PurePosixPath) -> bool:
    name = path.name
    if name in BAZEL_SOURCE_NAMES or name.startswith(".bazelrc."):
        return True
    if name.endswith((".bzl", ".bazel", ".MODULE.bazel")):
        return True
    return any(part.startswith("bazel-") for part in path.parts)


def snapshot_tree(workspace: pathlib.Path) -> dict[str, dict[str, Any]]:
    workspace = workspace.resolve()
    entries: dict[str, dict[str, Any]] = {}

    def visit(directory: pathlib.Path, relative: pathlib.PurePosixPath) -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            fail(f"cannot scan workspace directory {directory}: {exc}")
        for child in children:
            if not relative.parts and child.name == ".git":
                continue
            rel = relative / child.name
            rel_text = rel.as_posix()
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                fail(f"cannot stat workspace entry {rel_text}: {exc}")

            generated_root = len(rel.parts) == 1 and child.name in {
                "bazel-bin",
                "bazel-genfiles",
                "bazel-out",
                "bazel-testlogs",
            }
            generated_workspace_link = (
                len(rel.parts) == 1
                and child.name.startswith("bazel-")
                and stat.S_ISLNK(child_stat.st_mode)
            )
            if generated_root or generated_workspace_link:
                fail(f"pre-existing bazel-* tree is forbidden before guarded execution: {rel_text}")

            mode = stat.S_IMODE(child_stat.st_mode)
            if stat.S_ISDIR(child_stat.st_mode):
                entries[rel_text] = {"type": "directory", "mode": mode}
                visit(pathlib.Path(child.path), rel)
            elif stat.S_ISREG(child_stat.st_mode):
                entries[rel_text] = {
                    "type": "file",
                    "mode": mode,
                    "size": child_stat.st_size,
                    "sha256": sha256_file(pathlib.Path(child.path)),
                }
            elif stat.S_ISLNK(child_stat.st_mode):
                target = os.readlink(child.path)
                resolved = require_within(
                    workspace, pathlib.Path(child.path), f"symlink {rel_text}"
                )
                entries[rel_text] = {
                    "type": "symlink",
                    "mode": mode,
                    "target": target,
                    "resolved": resolved.relative_to(workspace).as_posix(),
                }
            else:
                fail(f"special filesystem entry is forbidden in guarded source: {rel_text}")

    visit(workspace, pathlib.PurePosixPath())
    return entries


def stable_snapshot(workspace: pathlib.Path) -> dict[str, dict[str, Any]]:
    first = snapshot_tree(workspace)
    second = snapshot_tree(workspace)
    if first != second:
        fail("workspace changed while the source snapshot was being established")
    return first


def snapshot_digest(entries: dict[str, Any]) -> str:
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def module_includes(path: pathlib.Path) -> list[str]:
    try:
        source = read_stable_text(path)
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (OSError, tokenize.TokenError) as exc:
        fail(f"cannot tokenize MODULE include source {path}: {exc}")

    includes: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type != tokenize.NAME or token.string != "include":
            index += 1
            continue
        index += 1
        while index < len(tokens) and tokens[index].type in {
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
        }:
            index += 1
        if index >= len(tokens) or tokens[index].string != "(":
            fail(f"MODULE include must be a static function call: {path}:{token.start[0]}")
        index += 1
        while index < len(tokens) and tokens[index].type == tokenize.NL:
            index += 1
        if index >= len(tokens) or tokens[index].type != tokenize.STRING:
            fail(f"MODULE include must use one literal label: {path}:{token.start[0]}")
        try:
            value = ast.literal_eval(tokens[index].string)
        except (ValueError, SyntaxError) as exc:
            fail(f"invalid MODULE include literal in {path}:{token.start[0]}: {exc}")
        if not isinstance(value, str):
            fail(f"MODULE include label must be a string: {path}:{token.start[0]}")
        index += 1
        while index < len(tokens) and tokens[index].type == tokenize.NL:
            index += 1
        if index >= len(tokens) or tokens[index].string != ")":
            fail(f"MODULE include must have exactly one literal argument: {path}:{token.start[0]}")
        includes.append(value)
        index += 1
    return includes


def resolve_module_label(workspace: pathlib.Path, label: str) -> pathlib.Path:
    if not label.startswith("//") or label.startswith("//@") or ".." in label.split("/"):
        fail(f"MODULE include must be a workspace-absolute label: {label}")
    body = label[2:]
    if ":" in body:
        package, name = body.split(":", 1)
        relative = pathlib.Path(package) / name
    else:
        relative = pathlib.Path(body)
    if not relative.name or relative.is_absolute():
        fail(f"invalid MODULE include label: {label}")
    candidate = workspace / relative
    if candidate.is_symlink():
        fail(f"MODULE include must not be a symlink: {label}")
    return require_within(workspace, candidate, f"MODULE include {label}")


def recursive_module_closure(workspace: pathlib.Path) -> set[pathlib.Path]:
    root = workspace / "MODULE.bazel"
    if not root.is_file():
        fail("MODULE.bazel is required for routine RBE")
    if root.is_symlink():
        fail("MODULE.bazel must not be a symlink")
    pending = [require_within(workspace, root, "MODULE.bazel")]
    visited: set[pathlib.Path] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for label in module_includes(current):
            included = resolve_module_label(workspace, label)
            if not included.is_file():
                fail(f"MODULE include is not a regular file: {label}")
            pending.append(included)
    return visited


def recursive_bazelrc_closure(workspace: pathlib.Path) -> set[pathlib.Path]:
    root = workspace / ".bazelrc"
    if not root.is_file():
        fail(".bazelrc is required for routine RBE")
    if root.is_symlink():
        fail(".bazelrc must not be a symlink")
    pending = [require_within(workspace, root, ".bazelrc")]
    visited: set[pathlib.Path] = set()
    import_re = re.compile(r"^\s*(?:try-)?import\s+(.+?)\s*$")
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        try:
            lines = read_stable_text(current).splitlines()
        except OSError as exc:
            fail(f"cannot read Bazel rc file {current}: {exc}")
        for line_number, line in enumerate(lines, start=1):
            match = import_re.match(line)
            if not match:
                continue
            raw = match.group(1).strip().replace("%workspace%", str(workspace))
            imported = pathlib.Path(raw)
            if not imported.is_absolute():
                imported = current.parent / imported
            lexical = pathlib.Path(os.path.abspath(imported))
            try:
                lexical.relative_to(workspace)
            except ValueError:
                fail(f"Bazel rc import escapes the workspace: {current}:{line_number}")
            try:
                if imported.is_symlink():
                    fail(f"Bazel rc import must not be a symlink: {current}:{line_number}")
                resolved = require_within(
                    workspace, imported, f"Bazel rc import {current}:{line_number}"
                )
            except GuardError:
                if line.lstrip().startswith("try-import") and not imported.exists():
                    continue
                raise
            pending.append(resolved)
    return visited


def scan_bazel_sources(workspace: pathlib.Path) -> dict[str, str]:
    module_files = recursive_module_closure(workspace)
    rc_files = recursive_bazelrc_closure(workspace)
    scanned: set[pathlib.Path] = set(module_files | rc_files)
    for path in workspace.rglob("*"):
        if ".git" in path.parts:
            continue
        try:
            relative = pathlib.PurePosixPath(path.relative_to(workspace).as_posix())
        except ValueError:
            fail(f"source scan escaped workspace: {path}")
        if is_bazel_source(relative):
            if path.is_symlink():
                fail(f"Bazel-facing source must not be a symlink: {relative}")
            if path.is_file():
                scanned.add(path.resolve())

    problems: list[str] = []
    audited_hashes: dict[str, str] = {}
    for path in sorted(scanned):
        try:
            data = read_stable_bytes(path)
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            fail(f"cannot read Bazel-facing source {path}: {exc}")
        relative = path.relative_to(workspace).as_posix()
        audited_hashes[relative] = sha256_bytes(data)
        searchable = "\n".join(
            "" if line.lstrip().startswith("#") else line
            for line in text.splitlines()
        )
        for pattern, description in FORBIDDEN_SOURCE_PATTERNS:
            for match in pattern.finditer(searchable):
                line_number = searchable.count("\n", 0, match.start()) + 1
                problems.append(
                    f"{relative}:{line_number}: forbidden {description}"
                )
    if problems:
        fail("source-purity scan failed:\n" + "\n".join(problems))
    return dict(sorted(audited_hashes.items()))


def validate_toolchain(workspace: pathlib.Path) -> dict[str, Any]:
    version_path = workspace / ".bazelversion"
    if not version_path.is_file():
        fail(".bazelversion is required for routine RBE")
    version = read_stable_text(version_path).strip()
    manifest = read_json(REPO_ROOT / "config/routine-rbe-toolchain.json")
    expected = manifest.get("bazel", {}).get("version")
    if version != expected:
        fail(f"consumer .bazelversion={version!r}; guarded toolchain requires {expected!r}")
    lock = workspace / "MODULE.bazel.lock"
    lock_data = read_json(lock)
    if not isinstance(lock_data, dict) or not isinstance(lock_data.get("lockFileVersion"), int):
        fail("MODULE.bazel.lock must be a Bazel lockfile with lockFileVersion")
    return manifest


def effective_lane_classes(lanes_path: pathlib.Path, lane_name: str) -> list[str]:
    data = read_json(lanes_path)
    if not isinstance(data, dict):
        fail("lanes.json root must be an object")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        fail("lanes.json defaults must be an object")
    default_classes = defaults.get("flywheel_target_classes") or []
    lanes = data.get("lanes")
    if not isinstance(lanes, list):
        fail("lanes.json lanes must be an array")
    matches = [lane for lane in lanes if isinstance(lane, dict) and lane.get("name") == lane_name]
    if len(matches) != 1:
        fail(f"lane {lane_name!r} must resolve exactly once in lanes.json")
    lane_classes = matches[0].get("flywheel_target_classes", default_classes)
    if not isinstance(lane_classes, list) or not all(isinstance(item, str) for item in lane_classes):
        fail("effective flywheel_target_classes must be an array of strings")
    return lane_classes


def validate_selection(
    workspace: pathlib.Path,
    lanes_path: pathlib.Path,
    lane_name: str,
    target_class: str,
    target: str,
    command: str,
) -> list[str]:
    expected_command = SUPPORTED_CLASSES.get(target_class)
    if expected_command is None:
        fail(f"unsupported routine-RBE target class: {target_class}")
    if command != expected_command:
        fail(f"target class {target_class} requires bazel_command={expected_command}")
    target_package = target[2:].split(":", 1)[0]
    if (
        not TARGET_RE.fullmatch(target)
        or ".." in target_package.split("/")
        or target in {"//...", "//:*"}
    ):
        fail(f"routine RBE requires one bounded canonical Bazel label, got {target!r}")
    classes = effective_lane_classes(lanes_path, lane_name)
    if target_class not in classes:
        fail(f"target class {target_class} is not admitted by lane {lane_name}")
    return classes


def source_scan(args: argparse.Namespace) -> None:
    workspace = pathlib.Path(args.workspace).resolve(strict=True)
    lanes_path = require_within(
        workspace, workspace / args.lanes_path, "lanes.json"
    )
    validate_selection(
        workspace,
        lanes_path,
        args.lane,
        args.target_class,
        args.target,
        args.bazel_command,
    )
    before = stable_snapshot(workspace)
    toolchain = validate_toolchain(workspace)
    bazel_source_hashes = scan_bazel_sources(workspace)
    lanes_relative = lanes_path.relative_to(workspace).as_posix()
    policy_input_hashes = {lanes_relative: sha256_file(lanes_path)}
    audited_workspace_hashes = dict(bazel_source_hashes)
    audited_workspace_hashes.update(policy_input_hashes)
    audited_workspace_hashes = dict(sorted(audited_workspace_hashes.items()))
    entries = stable_snapshot(workspace)
    if before != entries:
        fail("workspace changed while Bazel-facing source was being audited")
    for relative, digest in audited_workspace_hashes.items():
        entry = entries.get(relative)
        if not isinstance(entry, dict) or entry.get("type") != "file":
            fail(f"audited Bazel source is absent from the workspace snapshot: {relative}")
        if entry.get("sha256") != digest:
            fail(f"audited Bazel source changed before snapshot binding: {relative}")
    payload = {
        "schema_version": 1,
        "contract": CONTRACT_MARKER,
        "workspace_entries": entries,
        "workspace_digest": snapshot_digest(entries),
        "bazel_sources": sorted(bazel_source_hashes),
        "bazel_source_hashes": bazel_source_hashes,
        "policy_inputs": sorted(policy_input_hashes),
        "policy_input_hashes": policy_input_hashes,
        "audited_workspace_hashes": audited_workspace_hashes,
        "audited_workspace_digest": snapshot_digest(audited_workspace_hashes),
        "selection": {
            "lane": args.lane,
            "target_class": args.target_class,
            "target": args.target,
            "bazel_command": args.bazel_command,
        },
        "toolchain_contract": toolchain.get("contract"),
    }
    write_json(pathlib.Path(args.snapshot_out), payload)
    print(
        f"source purity verified: {len(entries)} entries, "
        f"{len(bazel_source_hashes)} Bazel-facing files, "
        f"{len(policy_input_hashes)} policy inputs, digest={payload['workspace_digest']}"
    )


def validate_audit_binding(snapshot: dict[str, Any]) -> dict[str, str]:
    entries = snapshot.get("workspace_entries")
    bazel_hashes = snapshot.get("bazel_source_hashes")
    policy_hashes = snapshot.get("policy_input_hashes")
    audited = snapshot.get("audited_workspace_hashes")
    sources = snapshot.get("bazel_sources")
    policy_inputs = snapshot.get("policy_inputs")
    if not all(
        isinstance(value, dict)
        for value in (entries, bazel_hashes, policy_hashes, audited)
    ):
        fail("source snapshot is missing its audited-workspace binding")
    if sources != sorted(bazel_hashes):
        fail("source snapshot Bazel source list differs from audited hashes")
    if policy_inputs != sorted(policy_hashes):
        fail("source snapshot policy input list differs from audited hashes")
    for label, hashes in (
        ("Bazel source", bazel_hashes),
        ("policy input", policy_hashes),
    ):
        for relative, digest in hashes.items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                fail(f"source snapshot contains a malformed {label} hash")
            if not SHA256_RE.fullmatch(digest):
                fail(f"source snapshot {label} hash is invalid for {relative}")
            entry = entries.get(relative)
            if not isinstance(entry, dict) or entry.get("sha256") != digest:
                fail(f"{label} hash is not bound to workspace snapshot: {relative}")
    overlap = set(bazel_hashes) & set(policy_hashes)
    if any(bazel_hashes[path] != policy_hashes[path] for path in overlap):
        fail("source snapshot has conflicting source and policy hashes")
    combined = dict(bazel_hashes)
    combined.update(policy_hashes)
    if dict(sorted(combined.items())) != audited:
        fail("source snapshot audited workspace differs from source and policy inputs")
    for relative, digest in audited.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            fail("source snapshot contains a malformed audited-workspace hash")
        if not SHA256_RE.fullmatch(digest):
            fail(f"source snapshot hash is invalid for {relative}")
        entry = entries.get(relative)
        if not isinstance(entry, dict) or entry.get("sha256") != digest:
            fail(f"audited-workspace hash is not bound to workspace snapshot: {relative}")
    if snapshot_digest(audited) != snapshot.get("audited_workspace_digest"):
        fail("audited-workspace digest changed")
    if snapshot.get("toolchain_contract") != CONTRACT_MARKER:
        fail("source snapshot has the wrong toolchain contract")
    return audited


def validate_snapshot_attestation(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or snapshot.get("contract") != CONTRACT_MARKER:
        fail("source snapshot has the wrong contract marker")
    if snapshot.get("schema_version") != 1:
        fail("source snapshot has an unsupported schema version")
    entries = snapshot.get("workspace_entries")
    if not isinstance(entries, dict):
        fail("source snapshot is missing workspace_entries")
    if snapshot_digest(entries) != snapshot.get("workspace_digest"):
        fail("workspace snapshot digest changed")
    selection = snapshot.get("selection")
    if not isinstance(selection, dict):
        fail("source snapshot is missing its execution selection")
    validate_audit_binding(snapshot)
    return snapshot


def source_verify(args: argparse.Namespace) -> None:
    workspace = pathlib.Path(args.workspace).resolve(strict=True)
    snapshot = validate_snapshot_attestation(read_json(pathlib.Path(args.snapshot)))
    expected = snapshot.get("workspace_entries")
    if not isinstance(expected, dict):
        fail("source snapshot is missing workspace_entries")
    actual = stable_snapshot(workspace)
    if actual != expected:
        expected_keys = set(expected)
        actual_keys = set(actual)
        details = []
        for path in sorted(expected_keys - actual_keys):
            details.append(f"removed: {path}")
        for path in sorted(actual_keys - expected_keys):
            details.append(f"added: {path}")
        for path in sorted(expected_keys & actual_keys):
            if expected[path] != actual[path]:
                details.append(f"changed: {path}")
        fail("workspace mutated after source scan:\n" + "\n".join(details[:40]))
    actual_digest = snapshot_digest(actual)
    if actual_digest != snapshot.get("workspace_digest"):
        fail("workspace snapshot digest changed")
    print(f"post-scan source stability verified: digest={actual_digest}")


def safe_git(candidate: str = "") -> str:
    fixed_candidates = (
        "/usr/bin/git",
        "/bin/git",
        "/run/current-system/sw/bin/git",
        "/nix/var/nix/profiles/default/bin/git",
    )
    if os.environ.get("TIN2851_SELFTEST") == "1":
        candidate = candidate or os.environ.get("TIN2851_SELFTEST_GIT", "")
    else:
        if candidate and candidate not in fixed_candidates:
            fail("git bootstrap must use a fixed system path")
        candidate = candidate or next(
            (
                fixed
                for fixed in fixed_candidates
                if pathlib.Path(fixed).is_file() and os.access(fixed, os.X_OK)
            ),
            "",
        )
    path = pathlib.Path(candidate)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        fail("git bootstrap must resolve to an absolute regular executable")
    resolved = path.resolve(strict=True)
    if os.environ.get("TIN2851_SELFTEST") == "1":
        return str(resolved)
    trusted_roots = tuple(
        root.resolve()
        for root in (pathlib.Path("/usr/bin"), pathlib.Path("/bin"), pathlib.Path("/nix/store"))
        if root.exists()
    )
    if not any(resolved.is_relative_to(root) for root in trusted_roots):
        fail("git bootstrap must resolve outside caller-controlled PATH locations")
    return str(resolved)


def git_environment(git_path: str, home: pathlib.Path) -> dict[str, str]:
    environment = {
        "PATH": str(pathlib.Path(git_path).parent),
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
    }
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "NIX_SSL_CERT_FILE"):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return environment


def run_git(git_path: str, home: pathlib.Path, arguments: Iterable[str], cwd: pathlib.Path | None = None) -> str:
    process = subprocess.run(
        [git_path, *arguments],
        cwd=cwd,
        env=git_environment(git_path, home),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode:
        fail(f"git {' '.join(arguments)} failed: {process.stderr.strip()}")
    return process.stdout


def remote_for_mode() -> str:
    override = os.environ.get("TIN2851_SELFTEST_REMOTE", "")
    if override:
        if os.environ.get("TIN2851_SELFTEST") != "1":
            fail("canonical remote overrides are selftest-only")
        return override
    return CANONICAL_REMOTE


def list_refs(git_path: str, home: pathlib.Path, remote: str, patterns: list[str]) -> dict[str, str]:
    output = run_git(git_path, home, ["ls-remote", "--tags", remote, *patterns])
    refs: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t", 1)
        if len(fields) != 2 or not SHA1_RE.fullmatch(fields[0]):
            fail(f"unexpected git ls-remote output: {line!r}")
        if fields[1] in refs and refs[fields[1]] != fields[0]:
            fail(f"remote returned contradictory values for {fields[1]}")
        refs[fields[1]] = fields[0]
    return refs


def require_annotated_pair(refs: dict[str, str], tag: str) -> tuple[str, str]:
    direct_name = f"refs/tags/{tag}"
    peeled_name = f"{direct_name}^{{}}"
    direct = refs.get(direct_name)
    peeled = refs.get(peeled_name)
    if not direct or not peeled:
        fail(f"{tag} must be an annotated tag with a separately advertised peeled commit")
    if direct == peeled:
        fail(f"{tag} direct tag object must differ from its peeled commit")
    return direct, peeled


def parse_workflow_ref(workflow_ref: str) -> str:
    prefix = f"{CANONICAL_REPOSITORY}/{CANONICAL_WORKFLOW}@refs/tags/"
    if not workflow_ref.startswith(prefix):
        fail(
            "routine RBE must run from the canonical reusable-workflow root "
            f"{CANONICAL_REPOSITORY}/{CANONICAL_WORKFLOW} at an explicit refs/tags ref"
        )
    ref = workflow_ref[len(prefix) :]
    if not SEMVER_V2_RE.fullmatch(ref):
        fail("routine RBE reusable workflow must be pinned to an exact immutable v2.x.y tag")
    if ref != ROUTINE_RBE_RELEASE_TAG:
        fail(
            "routine RBE reusable workflow must use the release that owns the "
            f"guarded action: {ROUTINE_RBE_RELEASE_TAG}"
        )
    return ref


def secure_extract_tar(data: bytes, destination: pathlib.Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                fail(f"git archive contains unsafe path: {member.name}")
            if not (member.isfile() or member.isdir() or member.issym()):
                fail(f"git archive contains unsupported entry: {member.name}")
            if member.issym():
                link = pathlib.PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts:
                    fail(f"git archive contains unsafe symlink: {member.name}")
        archive.extractall(destination, filter="data")


def fetch_archive(
    git_path: str,
    home: pathlib.Path,
    remote: str,
    tags: list[str],
    expected_refs: dict[str, str],
    destination: pathlib.Path,
) -> None:
    bare = destination.parent / "source.git"
    run_git(git_path, home, ["init", "--bare", str(bare)])
    refspecs = [f"+refs/tags/{tag}:refs/tags/{tag}" for tag in tags]
    run_git(git_path, home, ["-C", str(bare), "fetch", "--no-tags", "--depth=1", remote, *refspecs])
    for tag in tags:
        direct = run_git(git_path, home, ["-C", str(bare), "rev-parse", f"refs/tags/{tag}"]).strip()
        peeled = run_git(git_path, home, ["-C", str(bare), "rev-parse", f"refs/tags/{tag}^{{commit}}"]).strip()
        object_type = run_git(git_path, home, ["-C", str(bare), "cat-file", "-t", direct]).strip()
        if object_type != "tag":
            fail(f"fetched {tag} is not an annotated tag object")
        if direct != expected_refs[f"refs/tags/{tag}"]:
            fail(f"{tag} moved between remote snapshot and fetch")
        if peeled != expected_refs[f"refs/tags/{tag}^{{}}"]:
            fail(f"{tag} peeled commit changed between remote snapshot and fetch")
    archive = subprocess.run(
        [git_path, "-C", str(bare), "archive", "--format=tar", f"refs/tags/{tags[0]}^{{commit}}"],
        env=git_environment(git_path, home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if archive.returncode:
        fail(f"git archive failed: {archive.stderr.decode(errors='replace').strip()}")
    secure_extract_tar(archive.stdout, destination)


def file_hashes(root: pathlib.Path, relatives: Iterable[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in relatives:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            fail(f"trusted release file is missing or not a regular file: {relative}")
        hashes[relative] = sha256_file(path)
    return hashes


def helper_hashes(root: pathlib.Path) -> dict[str, str]:
    return file_hashes(root, HASHED_HELPERS)


def release_hashes(root: pathlib.Path) -> dict[str, str]:
    return file_hashes(root, AUDITED_RELEASE_FILES)


def validate_toolchain_manifest(root: pathlib.Path) -> dict[str, Any]:
    manifest = read_json(root / "config/routine-rbe-toolchain.json")
    if manifest.get("schema_version") != 1 or manifest.get("contract") != CONTRACT_MARKER:
        fail("routine-RBE toolchain manifest has the wrong contract marker")
    for tool in ("python", "bazelisk", "bazel"):
        block = manifest.get(tool)
        if not isinstance(block, dict):
            fail(f"toolchain manifest is missing {tool}")
        digest = block.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            fail(f"toolchain manifest {tool}.sha256 is not pinned")
    for tool in ("python", "bazelisk"):
        url = manifest[tool].get("url")
        if not isinstance(url, str) or not url.startswith("https://github.com/") or "/latest/" in url:
            fail(f"toolchain manifest {tool}.url must be an exact HTTPS release URL")
    return manifest


def trust_resolve(args: argparse.Namespace) -> None:
    if args.action_repository != CANONICAL_REPOSITORY:
        fail("routine-rbe action repository is not canonical")
    if args.action_ref != ROUTINE_RBE_RELEASE_TAG:
        fail(
            "routine-rbe action must be loaded from the exact release tag "
            f"@{ROUTINE_RBE_RELEASE_TAG}"
        )
    job_identity = {
        "workflow_ref": args.job_workflow_ref,
        "workflow_sha": args.job_workflow_sha,
        "workflow_repository": args.job_workflow_repository,
        "workflow_file_path": args.job_workflow_file_path,
    }
    supplied_identity = {
        "workflow_ref": args.workflow_ref,
        "workflow_sha": args.workflow_sha,
        "workflow_repository": args.workflow_repository,
        "workflow_file_path": args.workflow_file_path,
    }
    if supplied_identity != job_identity:
        fail("reusable-workflow identity inputs differ from the runner job context")
    if args.workflow_repository != CANONICAL_REPOSITORY:
        fail("job.workflow_repository is not the canonical ci-templates repository")
    if args.workflow_file_path != CANONICAL_WORKFLOW:
        fail("job.workflow_file_path is not the canonical reusable workflow")
    workflow_tag = parse_workflow_ref(args.workflow_ref)
    workflow_sha = args.workflow_sha.lower()
    if not SHA1_RE.fullmatch(workflow_sha):
        fail("job.workflow_sha must be a 40-character commit SHA")

    loaded_root = REPO_ROOT
    if pathlib.Path(args.workspace).resolve() == loaded_root:
        fail("consumer workspace cannot substitute for the loaded action source root")
    expected = {
        "scripts/routine-rbe-run.sh": args.run_sha256,
        "scripts/routine-rbe-guard.py": args.guard_sha256,
        "config/routine-rbe-toolchain.json": args.toolchain_sha256,
    }
    for relative, digest in expected.items():
        if not SHA256_RE.fullmatch(digest):
            fail(f"expected helper hash is invalid for {relative}")
        actual = sha256_file(loaded_root / relative)
        if actual != digest:
            fail(f"loaded helper hash mismatch for {relative}: {actual} != {digest}")

    trusted_root = pathlib.Path(args.trusted_root).resolve()
    trusted_root.mkdir(parents=True, exist_ok=True)
    home = trusted_root / "git-home"
    home.mkdir(mode=0o700)
    git_path = safe_git(args.git_path)
    remote = remote_for_mode()
    patterns = [
        f"refs/tags/{workflow_tag}",
        f"refs/tags/{workflow_tag}^{{}}",
    ]
    refs = list_refs(git_path, home, remote, patterns)
    release_object, release_commit = require_annotated_pair(refs, workflow_tag)
    if release_commit != workflow_sha:
        fail(
            "exact action/workflow release and job.workflow_sha must identify one "
            f"commit ({workflow_tag}={release_commit}, job={workflow_sha})"
        )

    archive_root = trusted_root / "canonical-source"
    fetch_archive(
        git_path,
        home,
        remote,
        [workflow_tag],
        refs,
        archive_root,
    )
    archive_hashes = helper_hashes(archive_root)
    loaded_hashes = helper_hashes(loaded_root)
    if archive_hashes != loaded_hashes or archive_hashes != expected:
        fail("loaded action helpers do not hash-match the canonical commit archive")
    archived_release = release_hashes(archive_root)
    loaded_release = release_hashes(loaded_root)
    if archived_release != loaded_release:
        fail("loaded action/workflow release files do not match the canonical commit archive")
    manifest = validate_toolchain_manifest(archive_root)
    if manifest.get("python", {}).get("url") != args.python_url:
        fail("bootstrap Python URL differs from the canonical toolchain manifest")
    if manifest.get("python", {}).get("sha256") != args.python_sha256:
        fail("bootstrap Python hash differs from the canonical toolchain manifest")

    state = {
        "schema_version": 1,
        "contract": CONTRACT_MARKER,
        "remote": remote,
        "action_repository": args.action_repository,
        "action_ref": args.action_ref,
        "action_tag": workflow_tag,
        "action_tag_object": release_object,
        "workflow_tag": workflow_tag,
        "workflow_tag_object": release_object,
        "peeled_commit": release_commit,
        "refs": refs,
        "helper_hashes": archive_hashes,
        "release_hashes": archived_release,
        "release_digest": snapshot_digest(archived_release),
        "archive_root": str(archive_root),
        "loaded_root": str(loaded_root),
        "git_path": git_path,
        "git_home": str(home),
        "workflow_repository": args.workflow_repository,
        "workflow_file_path": args.workflow_file_path,
        "workflow_ref": args.workflow_ref,
        "workflow_sha": workflow_sha,
    }
    write_json(pathlib.Path(args.state_out), state)
    print(
        "canonical source verified: "
        f"exact-tag={workflow_tag}, tag-object={release_object}, commit={release_commit}"
    )


def trust_recheck(args: argparse.Namespace) -> None:
    state = validate_trust_attestation(read_json(pathlib.Path(args.state)))
    git_path = state.get("git_path")
    home = pathlib.Path(state.get("git_home", ""))
    remote = state.get("remote")
    workflow_tag = state.get("workflow_tag")
    if remote != remote_for_mode():
        fail("trust-state remote differs from the canonical remote")
    patterns = [
        f"refs/tags/{workflow_tag}",
        f"refs/tags/{workflow_tag}^{{}}",
    ]
    current_refs = list_refs(git_path, home, remote, patterns)
    if current_refs != state.get("refs"):
        fail("canonical tag refs moved after the initial source verification")
    archive_root = pathlib.Path(state["archive_root"])
    loaded_root = pathlib.Path(state["loaded_root"])
    archive_hashes = helper_hashes(archive_root)
    loaded_hashes = helper_hashes(loaded_root)
    if archive_hashes != state.get("helper_hashes") or loaded_hashes != archive_hashes:
        fail("trusted helper source mutated after canonical verification")
    archived_release = release_hashes(archive_root)
    loaded_release = release_hashes(loaded_root)
    if archived_release != state.get("release_hashes") or loaded_release != archived_release:
        fail("trusted action/workflow release source mutated after canonical verification")
    if snapshot_digest(archived_release) != state.get("release_digest"):
        fail("trusted release digest changed after canonical verification")
    print("canonical refs and trusted release hashes remained stable")


def publication_check(args: argparse.Namespace) -> None:
    if os.environ.get("ROUTINE_RBE_TRUSTED_ROOT"):
        fail("local trusted-root substitution is forbidden for the publication gate")
    git_path = safe_git(getattr(args, "git_path", ""))
    remote = remote_for_mode()
    with tempfile.TemporaryDirectory(prefix="tin2851-publication-") as temporary:
        root = pathlib.Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        refs = list_refs(
            git_path,
            home,
            remote,
            [
                f"refs/tags/{ROUTINE_RBE_RELEASE_TAG}",
                f"refs/tags/{ROUTINE_RBE_RELEASE_TAG}^{{}}",
            ],
        )
        release_object, release_commit = require_annotated_pair(
            refs, ROUTINE_RBE_RELEASE_TAG
        )
        archive_root = root / "canonical-source"
        fetch_archive(
            git_path,
            home,
            remote,
            [ROUTINE_RBE_RELEASE_TAG],
            refs,
            archive_root,
        )
        manifest = validate_toolchain_manifest(archive_root)
        action_path = archive_root / ".github/actions/routine-rbe/action.yml"
        workflow_path = archive_root / CANONICAL_WORKFLOW
        if not action_path.is_file() or not workflow_path.is_file():
            fail("canonical exact-release archive does not publish the TIN-2851 routine-RBE guard")
        action_text = action_path.read_text(encoding="utf-8")
        workflow_text = workflow_path.read_text(encoding="utf-8")
        required_action = (
            "workflow-ref:\n",
            "workflow-sha:\n",
            "workflow-repository:\n",
            "workflow-file-path:\n",
            "ROUTINE_RBE_ACTION_REF: ${{ github.action_ref }}",
            "ROUTINE_RBE_JOB_WORKFLOW_REF: ${{ job.workflow_ref }}",
            '"$trusted_env" -i "${clean_env[@]}"',
        )
        for snippet in required_action:
            if snippet not in action_text:
                fail(f"published action is missing identity/bootstrap snippet: {snippet}")
        declared = {
            key: digest for key, digest in ACTION_HASH_RE.findall(action_text)
        }
        expected_keys = {"RUN", "GUARD", "TOOLCHAIN"}
        if set(declared) != expected_keys:
            fail("published routine-rbe action does not declare all helper SHA-256 pins")
        actual = helper_hashes(archive_root)
        expected_hashes = {
            "scripts/routine-rbe-run.sh": declared["RUN"],
            "scripts/routine-rbe-guard.py": declared["GUARD"],
            "config/routine-rbe-toolchain.json": declared["TOOLCHAIN"],
        }
        if actual != expected_hashes:
            fail("published helper-source hashes do not match the canonical archive")
        required_workflow = (
            "routine_rbe:\n",
            "default: false",
            f"uses: tinyland-inc/ci-templates/.github/actions/routine-rbe@{ROUTINE_RBE_RELEASE_TAG}",
            "workflow-ref: ${{ job.workflow_ref }}",
            "workflow-sha: ${{ job.workflow_sha }}",
            "workflow-repository: ${{ job.workflow_repository }}",
            "workflow-file-path: ${{ job.workflow_file_path }}",
        )
        for snippet in required_workflow:
            if snippet not in workflow_text:
                fail(f"published workflow is missing routine-RBE guard snippet: {snippet}")
        after = list_refs(
            git_path,
            home,
            remote,
            [
                f"refs/tags/{ROUTINE_RBE_RELEASE_TAG}",
                f"refs/tags/{ROUTINE_RBE_RELEASE_TAG}^{{}}",
            ],
        )
        if after != refs:
            fail("canonical exact release ref moved during publication verification")
        print(
            "routine-RBE publication gate passed: "
            f"exact-tag={ROUTINE_RBE_RELEASE_TAG}, tag-object={release_object}, "
            f"commit={release_commit}, bazel={manifest['bazel']['version']}"
        )


def artifact_verify(args: argparse.Namespace) -> None:
    if not SHA256_RE.fullmatch(args.sha256):
        fail("artifact SHA-256 pin must be 64 lowercase hexadecimal characters")
    actual = sha256_file(pathlib.Path(args.path))
    if actual != args.sha256:
        fail(f"{args.name} SHA-256 mismatch: expected {args.sha256}, got {actual}")
    print(f"artifact hash verified: {args.name}={actual}")


def option_value(options: list[str], name: str) -> str | None:
    result: str | None = None
    positive = f"--{name}"
    negative = f"--no{name}"
    for option in options:
        if option == positive:
            result = "true"
        elif option == negative:
            result = "false"
        elif option.startswith(positive + "="):
            result = option.split("=", 1)[1]
    return result


def load_bep(path: pathlib.Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    fail(f"BEP line {line_number} is not an object")
                events.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read Bazel BEP JSON: {exc}")
    if not events:
        fail("Bazel BEP JSON is empty")
    return events


def single_payload(events: list[dict[str, Any]], key: str) -> dict[str, Any]:
    matches = [event[key] for event in events if isinstance(event.get(key), dict)]
    if len(matches) != 1:
        fail(f"BEP must contain exactly one {key} payload")
    return matches[0]


def validate_trust_attestation(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("contract") != CONTRACT_MARKER:
        fail("trust state does not carry the TIN-2851 contract marker")
    if state.get("schema_version") != 1:
        fail("trust state has an unsupported schema version")
    if state.get("action_repository") != CANONICAL_REPOSITORY:
        fail("trust state action repository is not canonical")
    if state.get("action_ref") != ROUTINE_RBE_RELEASE_TAG:
        fail("trust state action ref is not the exact routine-RBE release")
    if state.get("action_tag") != ROUTINE_RBE_RELEASE_TAG:
        fail("trust state action tag differs from the exact release")
    if state.get("workflow_tag") != ROUTINE_RBE_RELEASE_TAG:
        fail("trust state workflow tag differs from the exact release")
    if state.get("workflow_repository") != CANONICAL_REPOSITORY:
        fail("trust state workflow repository is not canonical")
    if state.get("workflow_file_path") != CANONICAL_WORKFLOW:
        fail("trust state workflow path is not canonical")
    if parse_workflow_ref(str(state.get("workflow_ref", ""))) != ROUTINE_RBE_RELEASE_TAG:
        fail("trust state workflow ref is not canonical")
    workflow_sha = state.get("workflow_sha")
    peeled_commit = state.get("peeled_commit")
    if not isinstance(workflow_sha, str) or not SHA1_RE.fullmatch(workflow_sha):
        fail("trust state workflow SHA is invalid")
    if workflow_sha != peeled_commit:
        fail("trust state workflow SHA differs from its peeled release commit")
    action_object = state.get("action_tag_object")
    workflow_object = state.get("workflow_tag_object")
    if (
        not isinstance(action_object, str)
        or not SHA1_RE.fullmatch(action_object)
        or action_object != workflow_object
    ):
        fail("trust state action/workflow tag objects differ")
    release = state.get("release_hashes")
    helpers = state.get("helper_hashes")
    if not isinstance(release, dict) or set(release) != set(AUDITED_RELEASE_FILES):
        fail("trust state release hash set is incomplete")
    if not isinstance(helpers, dict) or set(helpers) != set(HASHED_HELPERS):
        fail("trust state helper hash set is incomplete")
    for relative, digest in release.items():
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            fail(f"trust state release hash is invalid for {relative}")
    if helpers != {relative: release[relative] for relative in HASHED_HELPERS}:
        fail("trust state helper hashes differ from the release hash set")
    if snapshot_digest(release) != state.get("release_digest"):
        fail("trust state release digest changed")
    return state


def attestation_metadata(
    snapshot: dict[str, Any], trust_state: dict[str, Any]
) -> dict[str, str]:
    selection = snapshot["selection"]
    values = {
        "contract": CONTRACT_MARKER,
        "action_repository": trust_state["action_repository"],
        "action_ref": trust_state["action_ref"],
        "workflow_repository": trust_state["workflow_repository"],
        "workflow_file_path": trust_state["workflow_file_path"],
        "workflow_ref": trust_state["workflow_ref"],
        "workflow_sha": trust_state["workflow_sha"],
        "release_digest": trust_state["release_digest"],
        "workspace_digest": snapshot["workspace_digest"],
        "audited_workspace_digest": snapshot["audited_workspace_digest"],
        "lane": selection["lane"],
        "target_class": selection["target_class"],
        "target": selection["target"],
        "bazel_command": selection["bazel_command"],
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        fail("attestation metadata contains an empty or non-string value")
    return {
        ATTESTATION_METADATA_KEYS[name]: value for name, value in values.items()
    }


def attestation_args(args: argparse.Namespace) -> None:
    snapshot = validate_snapshot_attestation(read_json(pathlib.Path(args.snapshot)))
    trust_state = validate_trust_attestation(
        read_json(pathlib.Path(args.trust_state))
    )
    for key, value in sorted(attestation_metadata(snapshot, trust_state).items()):
        print(f"--build_metadata={key}={value}")


def evidence_verify(args: argparse.Namespace) -> None:
    events = load_bep(pathlib.Path(args.bep))
    started = single_payload(events, "started")
    finished = single_payload(events, "finished")
    options = single_payload(events, "optionsParsed")
    metrics = single_payload(events, "buildMetrics")
    build_metadata = single_payload(events, "buildMetadata")

    toolchain_path = pathlib.Path(args.toolchain_manifest).resolve(strict=True)
    toolchain = validate_toolchain_manifest(toolchain_path.parents[1])
    expected_bazel = toolchain.get("bazel", {}).get("version")
    if started.get("buildToolVersion") != expected_bazel:
        fail(
            f"BEP Bazel version {started.get('buildToolVersion')!r} does not match "
            f"pinned {expected_bazel!r}"
        )
    if started.get("command") != args.bazel_command:
        fail("BEP command differs from the guarded Bazel command")
    exit_code = finished.get("exitCode")
    if not isinstance(exit_code, dict) or exit_code.get("code") != 0:
        fail("Bazel did not report a successful exit code")

    cmd_line = options.get("cmdLine")
    explicit = options.get("explicitCmdLine")
    if not isinstance(cmd_line, list) or not all(isinstance(item, str) for item in cmd_line):
        fail("BEP optionsParsed.cmdLine is missing")
    if not isinstance(explicit, list) or not all(isinstance(item, str) for item in explicit):
        fail("BEP optionsParsed.explicitCmdLine is missing")
    required_values = {
        "spawn_strategy": "remote",
        "remote_local_fallback": "false",
        "remote_accept_cached": "false",
        "remote_upload_local_results": "false",
        "disk_cache": "",
        "lockfile_mode": "error",
    }
    for name, expected in required_values.items():
        actual = option_value(cmd_line, name)
        if actual != expected:
            fail(f"effective Bazel option --{name} must be {expected!r}, got {actual!r}")
        if option_value(explicit, name) != expected:
            fail(f"Bazel option --{name} must be forced explicitly by the guarded invocation")
    for name in ("remote_executor", "remote_cache"):
        value = option_value(cmd_line, name)
        if not value or value in {"false", "true"}:
            fail(f"effective Bazel option --{name} must name a runtime endpoint")
        if option_value(explicit, name) != value:
            fail(f"Bazel option --{name} must come from the guarded runtime invocation")
    if option_value(cmd_line, "remote_executor") != option_value(cmd_line, "remote_cache"):
        fail("effective remote cache and executor endpoints must use one REAPI authority")

    action_summary = metrics.get("actionSummary")
    if not isinstance(action_summary, dict):
        fail("BEP buildMetrics.actionSummary is missing")
    runner_counts = action_summary.get("runnerCount")
    if not isinstance(runner_counts, list):
        fail("BEP actionSummary.runnerCount is missing")
    remote_processes = 0
    forbidden_local: dict[str, int] = {}
    cache_hits = 0
    for item in runner_counts:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            fail("BEP runnerCount entry is malformed")
        name = item["name"].strip().lower()
        count = item.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            fail(f"BEP runnerCount for {name!r} is not a non-negative integer")
        exec_kind_value = item.get("execKind")
        exec_kind = (
            exec_kind_value.strip().lower()
            if isinstance(exec_kind_value, str)
            else exec_kind_value
        )
        if exec_kind == "local" and count:
            forbidden_local[name] = count
        if name == "remote":
            if exec_kind not in (None, "remote"):
                fail("BEP remote runner has a non-remote execution kind")
            remote_processes += count
        elif "cache hit" in name:
            cache_hits += count
        elif name in {"local", "sandboxed", "linux-sandbox", "processwrapper-sandbox", "worker"} and count:
            forbidden_local[name] = count
    if remote_processes <= 0:
        fail(
            "remote_processes must be greater than zero; cache hits, ARC placement, "
            "and local execution are not RBE proof"
        )
    if cache_hits:
        fail("forced routine-RBE proof must not contain remote cache-hit processes")
    if forbidden_local:
        fail(f"forced routine-RBE proof contains local execution runners: {forbidden_local}")

    if args.bazel_command == "test":
        test_results = [event["testResult"] for event in events if isinstance(event.get("testResult"), dict)]
        if not test_results:
            fail("test-class proof is missing BEP testResult evidence")
        for result in test_results:
            execution = result.get("executionInfo")
            if not isinstance(execution, dict):
                fail("testResult is missing executionInfo")
            if execution.get("strategy") != "remote" or execution.get("cachedRemotely") is True:
                fail("every testResult must be remotely executed and not remotely cached")

    snapshot = validate_snapshot_attestation(read_json(pathlib.Path(args.snapshot)))
    trust_state = validate_trust_attestation(read_json(pathlib.Path(args.trust_state)))
    selection = snapshot.get("selection")
    expected_selection = {
        "lane": args.lane,
        "target_class": args.target_class,
        "target": args.target,
        "bazel_command": args.bazel_command,
    }
    if selection != expected_selection:
        fail("BEP evidence request differs from the source-scan selection")
    expected_metadata = attestation_metadata(snapshot, trust_state)
    actual_metadata = build_metadata.get("metadata")
    if actual_metadata != expected_metadata:
        fail("BEP build metadata differs from the trusted identity/source attestation")
    expected_metadata_flags = {
        f"--build_metadata={key}={value}" for key, value in expected_metadata.items()
    }
    if not expected_metadata_flags.issubset(set(explicit)):
        fail("identity/source attestation metadata was not forced by the guarded invocation")

    evidence = {
        "schema_version": 1,
        "claim": "bounded-routine-rbe",
        "claim_scope": "one admitted target class and one Bazel invocation",
        "not_proof_of": [
            "package authority",
            "remote cache attachment",
            "ARC runner placement",
            "product-wide RBE readiness",
            "CAS/action-cache publication authority",
        ],
        "target_class": args.target_class,
        "target": args.target,
        "bazel_command": args.bazel_command,
        "bazel_version": expected_bazel,
        "toolchain": {
            name: {
                "version": toolchain[name].get("version"),
                "sha256": toolchain[name]["sha256"],
            }
            for name in ("python", "bazelisk", "bazel")
        },
        "forced_remote_strategy": True,
        "local_fallback_disabled": True,
        "remote_cache_acceptance_disabled": True,
        "remote_processes": remote_processes,
        "source_digest": snapshot["workspace_digest"],
        "audited_workspace_digest": snapshot["audited_workspace_digest"],
        "audited_workspace_hashes": snapshot["audited_workspace_hashes"],
        "action_identity": {
            "repository": trust_state["action_repository"],
            "ref": trust_state["action_ref"],
            "tag_object": trust_state["action_tag_object"],
            "commit": trust_state["peeled_commit"],
        },
        "workflow_identity": {
            "repository": trust_state["workflow_repository"],
            "file_path": trust_state["workflow_file_path"],
            "ref": trust_state["workflow_ref"],
            "sha": trust_state["workflow_sha"],
            "tag_object": trust_state["workflow_tag_object"],
        },
        "ci_templates_tag": trust_state["workflow_tag"],
        "ci_templates_tag_object": trust_state["workflow_tag_object"],
        "ci_templates_commit": trust_state["peeled_commit"],
        "helper_hashes": trust_state.get("helper_hashes"),
        "release_hashes": trust_state["release_hashes"],
        "release_digest": trust_state["release_digest"],
        "bep_attestation_metadata": expected_metadata,
    }
    write_json(pathlib.Path(args.evidence_out), evidence)
    print(
        "bounded routine-RBE evidence verified: "
        f"target_class={args.target_class}, remote_processes={remote_processes}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("source-scan")
    scan.add_argument("--workspace", required=True)
    scan.add_argument("--lanes-path", required=True)
    scan.add_argument("--lane", required=True)
    scan.add_argument("--target-class", required=True)
    scan.add_argument("--target", required=True)
    scan.add_argument("--bazel-command", required=True)
    scan.add_argument("--snapshot-out", required=True)
    scan.set_defaults(handler=source_scan)

    verify = subparsers.add_parser("source-verify")
    verify.add_argument("--workspace", required=True)
    verify.add_argument("--snapshot", required=True)
    verify.set_defaults(handler=source_verify)

    trust = subparsers.add_parser("trust-resolve")
    trust.add_argument("--workspace", required=True)
    trust.add_argument("--trusted-root", required=True)
    trust.add_argument("--git-path", required=True)
    trust.add_argument("--action-repository", required=True)
    trust.add_argument("--action-ref", required=True)
    trust.add_argument("--workflow-ref", required=True)
    trust.add_argument("--workflow-sha", required=True)
    trust.add_argument("--workflow-repository", required=True)
    trust.add_argument("--workflow-file-path", required=True)
    trust.add_argument("--job-workflow-ref", required=True)
    trust.add_argument("--job-workflow-sha", required=True)
    trust.add_argument("--job-workflow-repository", required=True)
    trust.add_argument("--job-workflow-file-path", required=True)
    trust.add_argument("--run-sha256", required=True)
    trust.add_argument("--guard-sha256", required=True)
    trust.add_argument("--toolchain-sha256", required=True)
    trust.add_argument("--python-url", required=True)
    trust.add_argument("--python-sha256", required=True)
    trust.add_argument("--state-out", required=True)
    trust.set_defaults(handler=trust_resolve)

    recheck = subparsers.add_parser("trust-recheck")
    recheck.add_argument("--state", required=True)
    recheck.set_defaults(handler=trust_recheck)

    publication = subparsers.add_parser("publication-check")
    publication.add_argument("--git-path", default="")
    publication.set_defaults(handler=publication_check)

    artifact = subparsers.add_parser("artifact-verify")
    artifact.add_argument("--path", required=True)
    artifact.add_argument("--sha256", required=True)
    artifact.add_argument("--name", required=True)
    artifact.set_defaults(handler=artifact_verify)

    metadata = subparsers.add_parser("attestation-args")
    metadata.add_argument("--snapshot", required=True)
    metadata.add_argument("--trust-state", required=True)
    metadata.set_defaults(handler=attestation_args)

    evidence = subparsers.add_parser("evidence-verify")
    evidence.add_argument("--bep", required=True)
    evidence.add_argument("--snapshot", required=True)
    evidence.add_argument("--trust-state", required=True)
    evidence.add_argument("--toolchain-manifest", required=True)
    evidence.add_argument("--lane", required=True)
    evidence.add_argument("--target-class", required=True)
    evidence.add_argument("--target", required=True)
    evidence.add_argument("--bazel-command", required=True)
    evidence.add_argument("--evidence-out", required=True)
    evidence.set_defaults(handler=evidence_verify)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.handler(args)
    except GuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: guarded operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
