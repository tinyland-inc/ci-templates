#!/usr/bin/env python3
"""Fail-closed custody validation for the native Rust/Bazel runner binary."""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from pathlib import Path

NIX_BASE32 = "0123456789abcdfghijklmnpqrsvwxyz"
STORE_BASENAME_RE = re.compile(
    rf"^[{NIX_BASE32}]{{32}}-bazelisk-[A-Za-z0-9][A-Za-z0-9._+~-]*$"
)


class CustodyError(ValueError):
    """The runner fact is absent, mutable, or not the admitted binary."""


def validate_bazelisk(
    raw: str,
    *,
    store_root: Path = Path("/nix/store"),
    required_uid: int = 0,
) -> Path:
    if not raw or raw != raw.strip() or any(ord(char) < 32 for char in raw):
        raise CustodyError("TINYLAND_CI_BAZELISK_BIN must be one clean absolute path")
    path = Path(raw)
    if not path.is_absolute():
        raise CustodyError("TINYLAND_CI_BAZELISK_BIN must be absolute")
    expected_parent = store_root / path.parent.parent.name
    if path.parent.name != "bin" or path.name != "bazelisk":
        raise CustodyError("runner fact must name an unwrapped bin/bazelisk")
    if path.parent.parent.parent != store_root:
        raise CustodyError("runner Bazelisk must be a direct Nix store output")
    if not STORE_BASENAME_RE.fullmatch(path.parent.parent.name):
        raise CustodyError("runner Bazelisk store output has an invalid canonical name")
    if expected_parent / "bin" / "bazelisk" != path:
        raise CustodyError("runner Bazelisk path is not canonical")
    if path.resolve(strict=True) != path:
        raise CustodyError("runner Bazelisk path must not contain symlink indirection")
    for candidate in (path.parent.parent, path.parent, path):
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise CustodyError(
                "runner Bazelisk custody path must not contain a symlink"
            )
        if metadata.st_uid != required_uid:
            raise CustodyError("runner Bazelisk custody must be owned by root")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise CustodyError(
                "runner Bazelisk custody must not be group/world writable"
            )
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise CustodyError("runner Bazelisk must be a regular executable")
    return path


def write_output(path: Path, output: Path) -> None:
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"path={path}\n")


def self_test() -> int:
    with tempfile.TemporaryDirectory() as directory:
        # Darwin exposes /var through /private/var.  Build the fixture from its
        # canonical parent so the test exercises package indirection, not the
        # operating system's compatibility symlink.
        root = Path(directory).resolve() / "store"
        package = root / ("0" * 32 + "-bazelisk-1.28.1")
        binary = package / "bin" / "bazelisk"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        package.chmod(0o555)
        binary.parent.chmod(0o555)
        binary.chmod(0o555)
        assert (
            validate_bazelisk(str(binary), store_root=root, required_uid=os.getuid())
            == binary
        )

        for label, value in (
            ("absent", ""),
            ("relative", "store/bazelisk"),
            ("newline", f"{binary}\n/evil"),
            ("wrong output", str(root / ("0" * 32 + "-other-1") / "bin" / "bazelisk")),
        ):
            try:
                validate_bazelisk(value, store_root=root, required_uid=os.getuid())
            except (CustodyError, FileNotFoundError):
                pass
            else:
                raise AssertionError(f"{label} runner fact was admitted")

        binary.chmod(0o775)
        try:
            validate_bazelisk(str(binary), store_root=root, required_uid=os.getuid())
        except CustodyError:
            pass
        else:
            raise AssertionError("writable Bazelisk was admitted")
        binary.chmod(0o555)

        package.chmod(0o775)
        try:
            validate_bazelisk(str(binary), store_root=root, required_uid=os.getuid())
        except CustodyError:
            pass
        else:
            raise AssertionError("writable package ancestor was admitted")
        package.chmod(0o555)

        binary.parent.chmod(0o775)
        try:
            validate_bazelisk(str(binary), store_root=root, required_uid=os.getuid())
        except CustodyError:
            pass
        else:
            raise AssertionError("writable bin ancestor was admitted")
        binary.parent.chmod(0o555)

        try:
            validate_bazelisk(
                str(binary), store_root=root, required_uid=os.getuid() + 1
            )
        except CustodyError:
            pass
        else:
            raise AssertionError("wrong-owner Bazelisk was admitted")

        binary.chmod(0o444)
        try:
            validate_bazelisk(str(binary), store_root=root, required_uid=os.getuid())
        except CustodyError:
            pass
        else:
            raise AssertionError("non-executable Bazelisk was admitted")
        binary.chmod(0o555)

        target = package / "bin" / "bazelisk-target"
        binary.parent.chmod(0o755)
        binary.rename(target)
        binary.symlink_to(target.name)
        binary.parent.chmod(0o555)
        try:
            validate_bazelisk(str(binary), store_root=root, required_uid=os.getuid())
        except CustodyError:
            pass
        else:
            raise AssertionError("symlinked Bazelisk was admitted")
        binary.parent.chmod(0o755)
        binary.unlink()
        target.rename(binary)
        binary.parent.chmod(0o555)

        output = Path(directory) / "output"
        write_output(binary, output)
        assert output.read_text(encoding="utf-8") == f"path={binary}\n"
    print("rust-bazel binary custody self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.github_output is None:
        parser.error("--github-output is required")
    path = validate_bazelisk(os.environ.get("TINYLAND_CI_BAZELISK_BIN", ""))
    write_output(path, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
