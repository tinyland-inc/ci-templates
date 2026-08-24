#!/usr/bin/env python3
"""Seal and verify an immutable-release package artifact without executing it."""

from __future__ import annotations

import argparse
import ast
import base64
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import tarfile
from typing import Any
import zipfile


SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PACKAGE_RE = re.compile(
    r"^@[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$"
)
WORKFLOW_PATH_RE = re.compile(r"^\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml$")
REGISTRY = "https://npm.pkg.github.com"
SCHEMA_VERSION = 1
MAX_MEMBERS = 10_000
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


class ContractError(RuntimeError):
    """A release artifact or its source metadata violates the contract."""


def fail(message: str) -> None:
    raise ContractError(message)


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is not strict UTF-8 JSON: {exc}")


def load_json_file(path: pathlib.Path) -> Any:
    try:
        data = path.read_bytes()
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    return load_json_bytes(data, str(path))


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        fail(f"{label} keys mismatch (missing={missing}, extra={extra})")


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{label} must be a non-empty string")
    if any(character in value for character in ("\x00", "\r", "\n")):
        fail(f"{label} contains a forbidden control character")
    return value


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        fail(f"{label} must be a positive integer")
    return value


def validate_semver(value: str, label: str = "version") -> str:
    if SEMVER_RE.fullmatch(value) is None:
        fail(f"{label} must be canonical stable SemVer MAJOR.MINOR.PATCH")
    return value


def validate_repository(value: str) -> str:
    if REPOSITORY_RE.fullmatch(value) is None:
        fail("repository must be an owner/name coordinate")
    return value


def validate_sha(value: str, label: str = "source SHA") -> str:
    normalized = value.lower()
    if SHA_RE.fullmatch(normalized) is None:
        fail(f"{label} must be a full lowercase 40-character commit SHA")
    return normalized


def validate_package(value: str) -> str:
    if PACKAGE_RE.fullmatch(value) is None:
        fail("GitHub package name must be a lowercase scoped npm coordinate")
    return value


def validate_workflow_path(value: str) -> str:
    if WORKFLOW_PATH_RE.fullmatch(value) is None:
        fail("source workflow path must be a repository-relative .github/workflows YAML path")
    return value


def validate_owner_scope(repository: str, package_name: str) -> None:
    owner = repository.split("/", 1)[0].lower()
    scope = package_name.split("/", 1)[0][1:]
    if scope != owner:
        fail(f"GitHub package scope @{scope} must match repository owner {owner}")


def parse_starlark(path: pathlib.Path) -> ast.Module:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"cannot read Starlark file {path}: {exc}")
    try:
        return ast.parse(source, filename=str(path), mode="exec")
    except SyntaxError as exc:
        fail(f"{path} is not structurally parseable Starlark/Python syntax: {exc}")


def call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def keyword_string(call: ast.Call, keyword: str, label: str) -> str:
    values = [item.value for item in call.keywords if item.arg == keyword]
    if len(values) != 1:
        fail(f"{label} must declare exactly one {keyword}= string")
    value = values[0]
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        fail(f"{label} {keyword}= must be a literal string")
    return require_string(value.value, f"{label} {keyword}")


def unique_top_level_call(tree: ast.Module, name: str, label: str) -> ast.Call:
    calls: list[ast.Call] = []
    for statement in tree.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            if call_name(statement.value) == name:
                calls.append(statement.value)
    if len(calls) != 1:
        fail(f"{label} must contain exactly one top-level {name}(...) call")
    return calls[0]


def source_metadata(
    package_json_path: pathlib.Path,
    module_path: pathlib.Path,
    build_path: pathlib.Path,
) -> dict[str, str]:
    package_json = require_object(load_json_file(package_json_path), str(package_json_path))
    package_name = require_string(package_json.get("name"), "package.json name")
    package_version = validate_semver(
        require_string(package_json.get("version"), "package.json version"),
        "package.json version",
    )

    module_call = unique_top_level_call(parse_starlark(module_path), "module", str(module_path))
    module_name = keyword_string(module_call, "name", str(module_path))
    module_version = validate_semver(
        keyword_string(module_call, "version", str(module_path)),
        "MODULE.bazel module version",
    )

    build_tree = parse_starlark(build_path)
    package_calls: list[ast.Call] = []
    for statement in build_tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if call_name(call) != "npm_package":
            continue
        try:
            target_name = keyword_string(call, "name", str(build_path))
        except ContractError:
            continue
        if target_name == "pkg":
            package_calls.append(call)
    if len(package_calls) != 1:
        fail(f"{build_path} must contain exactly one top-level npm_package(name=\"pkg\") call")
    build_version = validate_semver(
        keyword_string(package_calls[0], "version", str(build_path)),
        "BUILD.bazel npm_package version",
    )

    versions = {package_version, module_version, build_version}
    if len(versions) != 1:
        fail(
            "release metadata version mismatch: "
            f"package.json={package_version}, MODULE.bazel={module_version}, "
            f"BUILD.bazel={build_version}"
        )
    return {
        "package_name": package_name,
        "module_name": module_name,
        "version": package_version,
    }


def safe_member_name(name: str, root: str | None = None) -> tuple[str, ...]:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        fail(f"unsafe tar member path: {name!r}")
    while name.startswith("./"):
        name = name[2:]
    path = pathlib.PurePosixPath(name)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        fail(f"unsafe tar member path: {name!r}")
    if root is not None and parts[0] != root:
        fail(f"tar member escapes expected root {root!r}: {name!r}")
    return parts


def read_regular_members(archive_path: pathlib.Path, root: str) -> dict[str, tuple[bytes, int]]:
    files: dict[str, tuple[bytes, int]] = {}
    unpacked_bytes = 0
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (OSError, tarfile.TarError) as exc:
        fail(f"cannot open {archive_path} as gzip tar: {exc}")
    with archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_MEMBERS:
            fail(f"archive member count must be between 1 and {MAX_MEMBERS}")
        for member in members:
            parts = safe_member_name(member.name, root)
            if member.isdir():
                continue
            if not member.isfile():
                fail(f"archive contains a non-regular member: {member.name}")
            relative_parts = parts[1:]
            if not relative_parts:
                fail(f"archive root is a regular file: {member.name}")
            relative = "/".join(relative_parts)
            if relative in files:
                fail(f"archive contains duplicate member path: {relative}")
            unpacked_bytes += member.size
            if unpacked_bytes > MAX_UNPACKED_BYTES:
                fail(f"archive exceeds {MAX_UNPACKED_BYTES} unpacked bytes")
            stream = archive.extractfile(member)
            if stream is None:
                fail(f"cannot read archive member: {member.name}")
            data = stream.read(MAX_UNPACKED_BYTES + 1)
            if len(data) != member.size:
                fail(f"archive member size mismatch: {member.name}")
            files[relative] = (data, member.mode)
    return files


def write_npm_tgz(files: dict[str, tuple[bytes, int]], output_path: pathlib.Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for relative in sorted(files):
                    data, original_mode = files[relative]
                    info = tarfile.TarInfo(name=f"package/{relative}")
                    info.size = len(data)
                    info.mode = 0o755 if original_mode & 0o111 else 0o644
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    archive.addfile(info, io.BytesIO(data))


def digest_file(path: pathlib.Path) -> tuple[str, str]:
    sha256 = hashlib.sha256()
    sha512 = hashlib.sha512()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha256.update(chunk)
                sha512.update(chunk)
    except OSError as exc:
        fail(f"cannot digest {path}: {exc}")
    integrity = "sha512-" + base64.b64encode(sha512.digest()).decode("ascii")
    return sha256.hexdigest(), integrity


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_output(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        for key, value in values.items():
            print(f"{key}={value}")
        return
    with open(output_path, "a", encoding="utf-8") as output:
        for key, value in values.items():
            print(f"{key}={value}", file=output)


def seal(args: argparse.Namespace) -> None:
    repository = validate_repository(args.repository)
    source_sha = validate_sha(args.source_sha)
    release_tag = require_string(args.release_tag, "release tag")
    github_package = validate_package(args.github_package)
    source_package = validate_package(args.source_package)
    module_name = require_string(args.module_name, "module name")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", module_name) is None:
        fail("module name contains unsupported characters")
    validate_owner_scope(repository, github_package)
    source_workflow_path = validate_workflow_path(args.source_workflow_path)
    source_run_id = require_positive_int(args.source_run_id, "source run id")
    source_run_attempt = require_positive_int(args.source_run_attempt, "source run attempt")

    metadata = source_metadata(
        pathlib.Path(args.package_json),
        pathlib.Path(args.module_bazel),
        pathlib.Path(args.build_bazel),
    )
    if metadata["package_name"] != source_package:
        fail(
            f"source package name {metadata['package_name']!r} does not match "
            f"expected {source_package!r}"
        )
    if metadata["module_name"] != module_name:
        fail(
            f"module name {metadata['module_name']!r} does not match "
            f"expected {module_name!r}"
        )
    version = metadata["version"]
    if release_tag != f"v{version}":
        fail(f"release tag {release_tag!r} must equal package version tag v{version}")

    package_root = pathlib.PurePosixPath(args.package_dir).name
    if not package_root or package_root in {".", ".."}:
        fail("package_dir must have a safe basename")
    files = read_regular_members(pathlib.Path(args.raw_archive), package_root)
    if "package.json" not in files:
        fail("Bazel package archive is missing package.json")
    built_package = require_object(
        load_json_bytes(files["package.json"][0], "Bazel package package.json"),
        "Bazel package package.json",
    )
    built_version = validate_semver(
        require_string(built_package.get("version"), "Bazel package version"),
        "Bazel package version",
    )
    if built_version != version:
        fail(f"Bazel package version {built_version} does not match source version {version}")
    built_package["name"] = github_package
    # The final publish payload is data only. Remove lifecycle hooks before the
    # artifact crosses into the package-write job; the verifier rejects any
    # later attempt to add them back.
    built_package.pop("scripts", None)
    publish_config = built_package.get("publishConfig")
    if publish_config is None:
        publish_config = {}
    publish_config = require_object(publish_config, "Bazel package publishConfig")
    publish_config["registry"] = REGISTRY
    built_package["publishConfig"] = publish_config
    files["package.json"] = (canonical_json_bytes(built_package), files["package.json"][1])

    output_dir = pathlib.Path(args.output_dir)
    package_path = output_dir / "package.tgz"
    manifest_path = output_dir / "release-metadata.json"
    write_npm_tgz(files, package_path)
    package_sha256, package_integrity = digest_file(package_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "source_sha": source_sha,
        "release_tag": release_tag,
        "source_run": {
            "id": source_run_id,
            "attempt": source_run_attempt,
            "workflow_path": source_workflow_path,
        },
        "package": {
            "file": package_path.name,
            "name": github_package,
            "version": version,
            "registry": REGISTRY,
            "sha256": package_sha256,
            "integrity": package_integrity,
        },
        "source_metadata": {
            "package_name": metadata["package_name"],
            "module_name": metadata["module_name"],
        },
    }
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    print(f"sealed {github_package}@{version} from {source_sha}")


def require_hex_digest(value: Any, length: int, label: str) -> str:
    digest = require_string(value, label).lower()
    if re.fullmatch(rf"[0-9a-f]{{{length}}}", digest) is None:
        fail(f"{label} must be {length} lowercase hexadecimal characters")
    return digest


def validate_final_tgz(
    package_path: pathlib.Path,
    package_name: str,
    version: str,
    registry: str,
) -> None:
    files = read_regular_members(package_path, "package")
    if "package.json" not in files:
        fail("final package.tgz is missing package/package.json")
    package_json = require_object(
        load_json_bytes(files["package.json"][0], "package.tgz package.json"),
        "package.tgz package.json",
    )
    if require_string(package_json.get("name"), "package.tgz name") != package_name:
        fail("package.tgz package name does not match release metadata")
    if validate_semver(
        require_string(package_json.get("version"), "package.tgz version"),
        "package.tgz version",
    ) != version:
        fail("package.tgz package version does not match release metadata")
    publish_config = require_object(package_json.get("publishConfig"), "package.tgz publishConfig")
    if require_string(publish_config.get("registry"), "package.tgz registry") != registry:
        fail("package.tgz publishConfig.registry does not match release metadata")
    if "scripts" in package_json:
        fail("package.tgz must not contain lifecycle scripts")


def unpack(args: argparse.Namespace) -> None:
    archive_path = pathlib.Path(args.archive)
    expected_digest = require_string(args.expected_digest, "artifact digest").lower()
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None:
        fail("artifact digest must be sha256:<64 lowercase hex characters>")
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        fail(f"cannot stat artifact archive: {exc}")
    if archive_size < 1 or archive_size > MAX_ARTIFACT_BYTES:
        fail(f"artifact archive size must be between 1 and {MAX_ARTIFACT_BYTES} bytes")
    actual_digest, _ = digest_file(archive_path)
    if expected_digest != f"sha256:{actual_digest}":
        fail("downloaded artifact ZIP digest does not match the GitHub artifact API digest")

    try:
        archive = zipfile.ZipFile(archive_path, mode="r")
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"cannot open artifact ZIP: {exc}")
    files: dict[str, bytes] = {}
    total_size = 0
    with archive:
        infos = archive.infolist()
        if len(infos) != 2:
            fail("artifact ZIP must contain exactly two files")
        for info in infos:
            parts = safe_member_name(info.filename)
            if len(parts) != 1 or info.is_dir():
                fail(f"artifact ZIP contains a nested or directory member: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in {0, 0o100000}:
                fail(f"artifact ZIP contains a non-regular member: {info.filename}")
            if info.flag_bits & 0x1:
                fail(f"artifact ZIP contains an encrypted member: {info.filename}")
            if info.filename in files:
                fail(f"artifact ZIP contains a duplicate member: {info.filename}")
            total_size += info.file_size
            if total_size > MAX_UNPACKED_BYTES:
                fail(f"artifact ZIP exceeds {MAX_UNPACKED_BYTES} unpacked bytes")
            data = archive.read(info)
            if len(data) != info.file_size:
                fail(f"artifact ZIP member size mismatch: {info.filename}")
            files[info.filename] = data
    if set(files) != {"package.tgz", "release-metadata.json"}:
        fail("artifact ZIP must contain exactly package.tgz and release-metadata.json")

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        fail("artifact output directory must be empty")
    for name, data in files.items():
        (output_dir / name).write_bytes(data)
    print(f"verified and unpacked GitHub artifact digest {expected_digest}")


def verify(args: argparse.Namespace) -> None:
    artifact_dir = pathlib.Path(args.artifact_dir)
    if not artifact_dir.is_dir():
        fail(f"artifact directory does not exist: {artifact_dir}")
    entries = sorted(path for path in artifact_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        fail("artifact directory may contain only regular files")
    if [path.name for path in entries] != ["package.tgz", "release-metadata.json"]:
        fail("artifact must contain exactly package.tgz and release-metadata.json")

    manifest_path = artifact_dir / "release-metadata.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = require_object(load_json_bytes(manifest_bytes, str(manifest_path)), "release metadata")
    if manifest_bytes != canonical_json_bytes(manifest):
        fail("release-metadata.json is not canonical JSON")
    require_exact_keys(
        manifest,
        {
            "schema_version",
            "repository",
            "source_sha",
            "release_tag",
            "source_run",
            "package",
            "source_metadata",
        },
        "release metadata",
    )
    if manifest["schema_version"] != SCHEMA_VERSION:
        fail(f"unsupported release metadata schema: {manifest['schema_version']!r}")

    repository = validate_repository(require_string(manifest["repository"], "repository"))
    source_sha = validate_sha(require_string(manifest["source_sha"], "source_sha"))
    release_tag = require_string(manifest["release_tag"], "release_tag")
    source_run = require_object(manifest["source_run"], "source_run")
    require_exact_keys(source_run, {"id", "attempt", "workflow_path"}, "source_run")
    source_run_id = require_positive_int(source_run["id"], "source_run.id")
    source_run_attempt = require_positive_int(source_run["attempt"], "source_run.attempt")
    source_workflow_path = validate_workflow_path(
        require_string(source_run["workflow_path"], "source_run.workflow_path")
    )

    package = require_object(manifest["package"], "package")
    require_exact_keys(
        package,
        {"file", "name", "version", "registry", "sha256", "integrity"},
        "package",
    )
    if package["file"] != "package.tgz":
        fail("package.file must be package.tgz")
    package_name = validate_package(require_string(package["name"], "package.name"))
    validate_owner_scope(repository, package_name)
    version = validate_semver(require_string(package["version"], "package.version"), "package.version")
    if release_tag != f"v{version}":
        fail("release_tag must equal v + package.version")
    registry = require_string(package["registry"], "package.registry")
    if registry != REGISTRY:
        fail(f"package.registry must be {REGISTRY}")
    package_sha256 = require_hex_digest(package["sha256"], 64, "package.sha256")
    package_integrity = require_string(package["integrity"], "package.integrity")

    source_metadata_value = require_object(manifest["source_metadata"], "source_metadata")
    require_exact_keys(source_metadata_value, {"module_name", "package_name"}, "source_metadata")
    require_string(source_metadata_value["module_name"], "source_metadata.module_name")
    require_string(source_metadata_value["package_name"], "source_metadata.package_name")

    expected = {
        "repository": args.repository,
        "source_sha": args.source_sha,
        "release_tag": args.release_tag,
        "source_workflow_path": args.source_workflow_path,
        "package_name": args.package_name,
    }
    actual = {
        "repository": repository,
        "source_sha": source_sha,
        "release_tag": release_tag,
        "source_workflow_path": source_workflow_path,
        "package_name": package_name,
    }
    for key, expected_value in expected.items():
        if expected_value is not None and actual[key] != expected_value:
            fail(f"artifact {key}={actual[key]!r}, expected {expected_value!r}")
    if args.source_run_id is not None and source_run_id != args.source_run_id:
        fail(f"artifact source_run_id={source_run_id}, expected {args.source_run_id}")
    if args.source_run_attempt is not None and source_run_attempt != args.source_run_attempt:
        fail(
            f"artifact source_run_attempt={source_run_attempt}, "
            f"expected {args.source_run_attempt}"
        )

    package_path = artifact_dir / "package.tgz"
    actual_sha256, actual_integrity = digest_file(package_path)
    if actual_sha256 != package_sha256 or actual_integrity != package_integrity:
        fail("package.tgz digest does not match release metadata")
    validate_final_tgz(package_path, package_name, version, registry)
    write_output(
        {
            "repository": repository,
            "source-sha": source_sha,
            "release-tag": release_tag,
            "source-run-id": str(source_run_id),
            "source-run-attempt": str(source_run_attempt),
            "source-workflow-path": source_workflow_path,
            "package-name": package_name,
            "package-version": version,
            "package-file": str(package_path),
            "package-sha256": package_sha256,
            "package-integrity": package_integrity,
        }
    )
    print(f"verified {package_name}@{version} from {source_sha}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)

    seal_parser = subparsers.add_parser("seal", help="seal a Bazel package archive")
    seal_parser.add_argument("--raw-archive", required=True)
    seal_parser.add_argument("--package-dir", required=True)
    seal_parser.add_argument("--package-json", required=True)
    seal_parser.add_argument("--module-bazel", required=True)
    seal_parser.add_argument("--build-bazel", required=True)
    seal_parser.add_argument("--repository", required=True)
    seal_parser.add_argument("--source-sha", required=True)
    seal_parser.add_argument("--release-tag", required=True)
    seal_parser.add_argument("--source-run-id", required=True, type=int)
    seal_parser.add_argument("--source-run-attempt", required=True, type=int)
    seal_parser.add_argument("--source-workflow-path", required=True)
    seal_parser.add_argument("--source-package", required=True)
    seal_parser.add_argument("--module-name", required=True)
    seal_parser.add_argument("--github-package", required=True)
    seal_parser.add_argument("--output-dir", required=True)
    seal_parser.set_defaults(func=seal)

    verify_parser = subparsers.add_parser("verify", help="verify a sealed release artifact")
    verify_parser.add_argument("--artifact-dir", required=True)
    verify_parser.add_argument("--repository")
    verify_parser.add_argument("--source-sha")
    verify_parser.add_argument("--release-tag")
    verify_parser.add_argument("--source-run-id", type=int)
    verify_parser.add_argument("--source-run-attempt", type=int)
    verify_parser.add_argument("--source-workflow-path")
    verify_parser.add_argument("--package-name")
    verify_parser.set_defaults(func=verify)

    unpack_parser = subparsers.add_parser(
        "unpack", help="digest-check and safely unpack a GitHub artifact ZIP"
    )
    unpack_parser.add_argument("--archive", required=True)
    unpack_parser.add_argument("--expected-digest", required=True)
    unpack_parser.add_argument("--output-dir", required=True)
    unpack_parser.set_defaults(func=unpack)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        args.func(args)
    except ContractError as exc:
        print(f"immutable-release metadata error: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
