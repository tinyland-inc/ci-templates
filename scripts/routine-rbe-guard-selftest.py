#!/usr/bin/env python3
"""Adversarial offline selftests for the TIN-2851 routine-RBE guard."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts/routine-rbe-guard.py"
RUNNER_PATH = ROOT / "scripts/routine-rbe-run.sh"
SPEC = importlib.util.spec_from_file_location("routine_rbe_guard", GUARD_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load routine-rbe guard")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class Suite:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def ok(self, name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001 - selftest reports all cases
            self.failed += 1
            print(f"FAIL {name}: {exc}")
        else:
            self.passed += 1
            print(f"ok   {name}")

    def rejects(self, name: str, fragment: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except guard.GuardError as exc:
            if fragment not in str(exc):
                self.failed += 1
                print(f"FAIL {name}: wrong error: {exc}")
                return
            self.passed += 1
            print(f"ok   {name}")
            return
        except Exception as exc:  # noqa: BLE001
            self.failed += 1
            print(f"FAIL {name}: unexpected exception: {exc}")
            return
        self.failed += 1
        print(f"FAIL {name}: guard accepted adversarial input")


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_workspace(root: pathlib.Path) -> pathlib.Path:
    workspace = root / "consumer"
    write(
        workspace / "MODULE.bazel",
        'module(name = "fixture", version = "0.0.0")\n'
        'include("//modules:deps.MODULE.bazel")\n'
        'include("//modules:first-party.inc")\n',
    )
    write(
        workspace / "modules/deps.MODULE.bazel",
        'bazel_dep(name = "platforms", version = "0.0.11")\n',
    )
    write(workspace / "modules/first-party.inc", "# included first-party policy\n")
    write(workspace / "MODULE.bazel.lock", '{"lockFileVersion": 18}\n')
    write(workspace / ".bazelversion", "8.2.1\n")
    write(workspace / ".bazelrc", "try-import %workspace%/.bazelrc.flywheel\n")
    write(
        workspace / ".bazelrc.flywheel",
        "common:flywheel-executor --spawn_strategy=remote\n"
        "common:flywheel-executor --remote_local_fallback=false\n",
    )
    write(
        workspace / "BUILD.bazel",
        'filegroup(name = "build", srcs = ["source.txt"], tags = ["flywheel-eligible"])\n',
    )
    write(workspace / "source.txt", "fixture\n")
    write(workspace / "tools/bazel-rules/README", "scanned Bazel helper tree\n")
    write(
        workspace / ".github/lanes.json",
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"flywheel_target_classes": ["sveltekit-app-build"]},
                "lanes": [{"name": "default"}],
            }
        )
        + "\n",
    )
    return workspace


def scan_args(workspace: pathlib.Path, snapshot: pathlib.Path, **overrides: str) -> argparse.Namespace:
    values = {
        "workspace": str(workspace),
        "lanes_path": ".github/lanes.json",
        "lane": "default",
        "target_class": "sveltekit-app-build",
        "target": "//:build",
        "bazel_command": "build",
        "snapshot_out": str(snapshot),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def require_audited(snapshot: pathlib.Path, relative: str) -> None:
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    if relative not in data.get("audited_workspace_hashes", {}):
        raise RuntimeError(f"{relative} is absent from audited workspace hashes")


def git(repository: pathlib.Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    return process.stdout.strip()


def helper_hashes() -> dict[str, str]:
    return guard.helper_hashes(ROOT)


def make_source_repo(
    root: pathlib.Path, *, complete: bool = True, lightweight_release: bool = False
) -> tuple[pathlib.Path, str]:
    repository = root / "source-repo"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "TIN-2851 Selftest")
    git(repository, "config", "user.email", "tin2851@example.invalid")
    write(repository / "README.md", "fixture\n")
    if complete:
        for relative in (
            *guard.HASHED_HELPERS,
            ".github/actions/routine-rbe/action.yml",
            ".github/workflows/spoke-ci.yml",
        ):
            source = ROOT / relative
            destination = repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    git(repository, "add", ".")
    git(repository, "commit", "-q", "-m", "fixture release")
    commit = git(repository, "rev-parse", "HEAD")
    if lightweight_release:
        git(repository, "tag", guard.ROUTINE_RBE_RELEASE_TAG)
    else:
        git(
            repository,
            "tag",
            "-a",
            guard.ROUTINE_RBE_RELEASE_TAG,
            "-m",
            guard.ROUTINE_RBE_RELEASE_TAG,
        )
    return repository, commit


@contextlib.contextmanager
def selftest_remote(repository: pathlib.Path) -> Iterator[None]:
    old_test = os.environ.get("TIN2851_SELFTEST")
    old_remote = os.environ.get("TIN2851_SELFTEST_REMOTE")
    old_git = os.environ.get("TIN2851_SELFTEST_GIT")
    os.environ["TIN2851_SELFTEST"] = "1"
    os.environ["TIN2851_SELFTEST_REMOTE"] = str(repository)
    os.environ["TIN2851_SELFTEST_GIT"] = shutil.which("git") or ""
    try:
        yield
    finally:
        for name, old in (
            ("TIN2851_SELFTEST", old_test),
            ("TIN2851_SELFTEST_REMOTE", old_remote),
            ("TIN2851_SELFTEST_GIT", old_git),
        ):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def trust_args(
    workspace: pathlib.Path,
    trusted_root: pathlib.Path,
    state: pathlib.Path,
    commit: str,
    **overrides: str,
) -> argparse.Namespace:
    hashes = helper_hashes()
    manifest = json.loads((ROOT / "config/routine-rbe-toolchain.json").read_text())
    values = {
        "workspace": str(workspace),
        "trusted_root": str(trusted_root),
        "git_path": shutil.which("git") or "",
        "action_repository": guard.CANONICAL_REPOSITORY,
        "action_ref": guard.ROUTINE_RBE_RELEASE_TAG,
        "workflow_ref": (
            "tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@refs/tags/"
            + guard.ROUTINE_RBE_RELEASE_TAG
        ),
        "workflow_sha": commit,
        "workflow_repository": guard.CANONICAL_REPOSITORY,
        "workflow_file_path": guard.CANONICAL_WORKFLOW,
        "job_workflow_ref": (
            "tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@refs/tags/"
            + guard.ROUTINE_RBE_RELEASE_TAG
        ),
        "job_workflow_sha": commit,
        "job_workflow_repository": guard.CANONICAL_REPOSITORY,
        "job_workflow_file_path": guard.CANONICAL_WORKFLOW,
        "run_sha256": hashes["scripts/routine-rbe-run.sh"],
        "guard_sha256": hashes["scripts/routine-rbe-guard.py"],
        "toolchain_sha256": hashes["config/routine-rbe-toolchain.json"],
        "python_url": manifest["python"]["url"],
        "python_sha256": manifest["python"]["sha256"],
        "state_out": str(state),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def bep_events(
    *,
    remote: int = 3,
    cache_hits: int = 0,
    local: int = 0,
    fallback: str = "false",
    spawn: str = "remote",
    bazel_version: str = "8.2.1",
    command: str = "build",
    test_cached: bool = False,
    metadata: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    metadata = metadata or {}
    flags = [
        f"--spawn_strategy={spawn}",
        f"--remote_local_fallback={fallback}",
        "--remote_accept_cached=false",
        "--remote_upload_local_results=false",
        "--remote_executor=grpc://executor.example:8980",
        "--remote_cache=grpc://executor.example:8980",
        "--disk_cache=",
        "--lockfile_mode=error",
        *(f"--build_metadata={key}={value}" for key, value in sorted(metadata.items())),
    ]
    runners = [{"name": "remote", "count": remote, "execKind": "remote"}]
    if cache_hits:
        runners.append({"name": "remote cache hit", "count": cache_hits, "execKind": "remote"})
    if local:
        runners.append({"name": "processwrapper-sandbox", "count": local, "execKind": "local"})
    events: list[dict[str, Any]] = [
        {"started": {"buildToolVersion": bazel_version, "command": command}},
        {"optionsParsed": {"cmdLine": flags, "explicitCmdLine": flags}},
        {"buildMetadata": {"metadata": metadata}},
        {"buildMetrics": {"actionSummary": {"runnerCount": runners}}},
    ]
    if command == "test":
        events.append(
            {
                "testResult": {
                    "executionInfo": {
                        "strategy": "remote",
                        "cachedRemotely": test_cached,
                    }
                }
            }
        )
    events.append(
        {"finished": {"overallSuccess": True, "exitCode": {"name": "SUCCESS", "code": 0}}}
    )
    return events


def write_bep(path: pathlib.Path, events: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def evidence_fixture(root: pathlib.Path, *, command: str = "build") -> argparse.Namespace:
    bep = root / "bep.json"
    snapshot = root / "snapshot.json"
    trust = root / "trust.json"
    evidence = root / "evidence.json"
    selection = {
        "lane": "default",
        "target_class": "sveltekit-unit-tests" if command == "test" else "sveltekit-app-build",
        "target": "//:unit_tests" if command == "test" else "//:build",
        "bazel_command": command,
    }
    source_digest = guard.sha256_bytes(b"module")
    policy_digest = guard.sha256_bytes(b"lanes")
    entries = {
        ".github/lanes.json": {
            "type": "file",
            "mode": 0o644,
            "size": 5,
            "sha256": policy_digest,
        },
        "MODULE.bazel": {
            "type": "file",
            "mode": 0o644,
            "size": 6,
            "sha256": source_digest,
        },
    }
    bazel_hashes = {"MODULE.bazel": source_digest}
    policy_hashes = {".github/lanes.json": policy_digest}
    audited_hashes = dict(sorted({**bazel_hashes, **policy_hashes}.items()))
    snapshot_data = {
        "schema_version": 1,
        "contract": guard.CONTRACT_MARKER,
        "workspace_entries": entries,
        "workspace_digest": guard.snapshot_digest(entries),
        "bazel_sources": sorted(bazel_hashes),
        "bazel_source_hashes": bazel_hashes,
        "policy_inputs": sorted(policy_hashes),
        "policy_input_hashes": policy_hashes,
        "audited_workspace_hashes": audited_hashes,
        "audited_workspace_digest": guard.snapshot_digest(audited_hashes),
        "selection": selection,
        "toolchain_contract": guard.CONTRACT_MARKER,
    }
    release_hashes = {relative: "d" * 64 for relative in guard.AUDITED_RELEASE_FILES}
    helper_hashes = {
        relative: release_hashes[relative] for relative in guard.HASHED_HELPERS
    }
    workflow_ref = (
        "tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@refs/tags/"
        + guard.ROUTINE_RBE_RELEASE_TAG
    )
    trust_data = {
        "schema_version": 1,
        "contract": guard.CONTRACT_MARKER,
        "action_repository": guard.CANONICAL_REPOSITORY,
        "action_ref": guard.ROUTINE_RBE_RELEASE_TAG,
        "action_tag": guard.ROUTINE_RBE_RELEASE_TAG,
        "action_tag_object": "b" * 40,
        "workflow_tag": guard.ROUTINE_RBE_RELEASE_TAG,
        "workflow_tag_object": "b" * 40,
        "peeled_commit": "c" * 40,
        "workflow_repository": guard.CANONICAL_REPOSITORY,
        "workflow_file_path": guard.CANONICAL_WORKFLOW,
        "workflow_ref": workflow_ref,
        "workflow_sha": "c" * 40,
        "helper_hashes": helper_hashes,
        "release_hashes": release_hashes,
        "release_digest": guard.snapshot_digest(release_hashes),
    }
    snapshot.write_text(json.dumps(snapshot_data) + "\n", encoding="utf-8")
    trust.write_text(json.dumps(trust_data) + "\n", encoding="utf-8")
    metadata = guard.attestation_metadata(snapshot_data, trust_data)
    write_bep(bep, bep_events(command=command, metadata=metadata))
    result = argparse.Namespace(
        bep=str(bep),
        snapshot=str(snapshot),
        trust_state=str(trust),
        toolchain_manifest=str(ROOT / "config/routine-rbe-toolchain.json"),
        lane=selection["lane"],
        target_class=selection["target_class"],
        target=selection["target"],
        bazel_command=command,
        evidence_out=str(evidence),
    )
    result.attestation_metadata = metadata
    return result


def bep_for(args: argparse.Namespace, **overrides: Any) -> list[dict[str, Any]]:
    return bep_events(metadata=args.attestation_metadata, **overrides)


def main() -> int:
    suite = Suite()
    with tempfile.TemporaryDirectory(prefix="tin2851-selftest-") as temporary:
        temp = pathlib.Path(temporary)

        workspace = make_workspace(temp / "source-happy")
        snapshot = temp / "source-happy/snapshot.json"
        suite.ok("recursive MODULE and Bazel-tree source scan accepts clean input", lambda: guard.source_scan(scan_args(workspace, snapshot)))
        suite.ok(
            "MODULE include source is bound into the audited workspace",
            lambda: require_audited(snapshot, "modules/first-party.inc"),
        )
        suite.ok(
            "lane policy is bound into the audited workspace",
            lambda: require_audited(snapshot, ".github/lanes.json"),
        )
        suite.ok(
            "unchanged source passes post-scan verification",
            lambda: guard.source_verify(argparse.Namespace(workspace=str(workspace), snapshot=str(snapshot))),
        )

        poisoned = make_workspace(temp / "module-poison")
        write(
            poisoned / "modules/first-party.inc",
            'local_path_override(module_name="x", path="../x")\n',
        )
        suite.rejects(
            "nonstandard MODULE include source cannot hide local_path_override",
            "local_path_override",
            lambda: guard.source_scan(scan_args(poisoned, temp / "module-poison/snapshot.json")),
        )

        multiline_poisoned = make_workspace(temp / "module-multiline-poison")
        write(
            multiline_poisoned / "modules/first-party.inc",
            'local_path_override\n(module_name="x", path="../x")\n',
        )
        suite.rejects(
            "multiline MODULE include source cannot hide local_path_override",
            "local_path_override",
            lambda: guard.source_scan(
                scan_args(
                    multiline_poisoned,
                    temp / "module-multiline-poison/snapshot.json",
                )
            ),
        )

        bazel_tree = make_workspace(temp / "bazel-tree-poison")
        write(bazel_tree / "tools/bazel-poison/hidden.txt", "--override_repository=x=/tmp/x\n")
        suite.rejects(
            "nested bazel-* tree cannot hide local repository injection",
            "local repository injection",
            lambda: guard.source_scan(scan_args(bazel_tree, temp / "bazel-tree-poison/snapshot.json")),
        )

        dynamic = make_workspace(temp / "dynamic-include")
        write(dynamic / "MODULE.bazel", 'name = "//modules:deps.MODULE.bazel"\ninclude(name)\n')
        suite.rejects(
            "dynamic MODULE include is rejected",
            "one literal label",
            lambda: guard.source_scan(scan_args(dynamic, temp / "dynamic-include/snapshot.json")),
        )

        rc_escape = make_workspace(temp / "rc-escape")
        write(rc_escape / ".bazelrc", "try-import ../outside.bazelrc\n")
        suite.rejects(
            "recursive bazelrc import cannot escape workspace",
            "escapes the workspace",
            lambda: guard.source_scan(scan_args(rc_escape, temp / "rc-escape/snapshot.json")),
        )

        generated = make_workspace(temp / "generated-tree")
        (generated / "bazel-out").mkdir()
        suite.rejects(
            "pre-existing bazel-* output tree is rejected",
            "pre-existing bazel-* tree",
            lambda: guard.source_scan(scan_args(generated, temp / "generated-tree/snapshot.json")),
        )

        unsupported = make_workspace(temp / "unsupported-class")
        suite.rejects(
            "candidate or unknown target class is rejected",
            "unsupported routine-RBE target class",
            lambda: guard.source_scan(
                scan_args(
                    unsupported,
                    temp / "unsupported-class/snapshot.json",
                    target_class="web-playwright-chromium-static-smoke",
                )
            ),
        )

        unadmitted = make_workspace(temp / "unadmitted-class")
        suite.rejects(
            "supported class absent from lane allowlist is rejected",
            "is not admitted by lane",
            lambda: guard.source_scan(
                scan_args(
                    unadmitted,
                    temp / "unadmitted-class/snapshot.json",
                    target_class="sveltekit-unit-tests",
                    target="//:unit_tests",
                    bazel_command="test",
                )
            ),
        )

        wrong_tool = make_workspace(temp / "wrong-tool")
        write(wrong_tool / ".bazelversion", "9.2.0\n")
        suite.rejects(
            "consumer cannot replace pinned Bazel version",
            "guarded toolchain requires",
            lambda: guard.source_scan(scan_args(wrong_tool, temp / "wrong-tool/snapshot.json")),
        )

        bash = shutil.which("bash") or "/bin/bash"
        syntax = subprocess.run(
            [bash, "-n", str(RUNNER_PATH)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        suite.ok(
            "routine runner has valid Bash syntax",
            lambda: (
                None
                if syntax.returncode == 0
                else (_ for _ in ()).throw(RuntimeError(syntax.stderr))
            ),
        )

        tool_shim_dir = temp / "runner-path-shim"
        tool_shim_dir.mkdir()
        tool_shim_sentinel = temp / "runner-path-shim-used"
        write(
            tool_shim_dir / "uname",
            f"#!/bin/sh\nprintf used > {str(tool_shim_sentinel)!r}\nexit 0\n",
        )
        (tool_shim_dir / "uname").chmod(0o755)
        sealed_runner = subprocess.run(
            [bash, "--noprofile", "--norc", str(RUNNER_PATH)],
            env={
                "PATH": str(tool_shim_dir),
                "BASH_ENV": os.devnull,
                "ENV": os.devnull,
                "ROUTINE_RBE_ENABLED": "true",
                "ROUTINE_RBE_CACHE_BACKED": "true",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        suite.ok(
            "routine runner ignores caller PATH tool shims",
            lambda: (
                None
                if sealed_runner.returncode != 0 and not tool_shim_sentinel.exists()
                else (_ for _ in ()).throw(
                    RuntimeError(sealed_runner.stderr or "caller PATH shim executed")
                )
            ),
        )

        mutated = make_workspace(temp / "post-scan-mutation")
        mutated_snapshot = temp / "post-scan-mutation/snapshot.json"
        guard.source_scan(scan_args(mutated, mutated_snapshot))
        write(mutated / "source.txt", "changed after scan\n")
        suite.rejects(
            "post-scan source mutation is detected",
            "workspace mutated after source scan",
            lambda: guard.source_verify(argparse.Namespace(workspace=str(mutated), snapshot=str(mutated_snapshot))),
        )

        artifact = temp / "artifact.bin"
        artifact.write_bytes(b"trusted")
        for tool_name in ("Python", "Bazelisk", "Bazel"):
            suite.rejects(
                f"wrong {tool_name} artifact hash is rejected",
                f"{tool_name} SHA-256 mismatch",
                lambda name=tool_name: guard.artifact_verify(
                    argparse.Namespace(path=str(artifact), sha256="0" * 64, name=name)
                ),
            )

        git_shim = temp / "path-shim/git"
        write(git_shim, "#!/bin/sh\nexit 0\n")
        git_shim.chmod(0o755)
        suite.rejects(
            "caller-controlled git path shim is rejected",
            "fixed system path",
            lambda: guard.safe_git(str(git_shim)),
        )

        poison_dir = temp / "python-poison"
        poison_dir.mkdir()
        sentinel = temp / "python-poisoned"
        write(poison_dir / "sitecustomize.py", f'import pathlib; pathlib.Path({str(sentinel)!r}).write_text("poisoned")\n')
        digest = guard.sha256_file(artifact)
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(GUARD_PATH),
                "artifact-verify",
                "--path",
                str(artifact),
                "--sha256",
                digest,
                "--name",
                "isolated-Python",
            ],
            env={**os.environ, "PYTHONPATH": str(poison_dir), "PYTHONHOME": ""},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        suite.ok(
            "isolated Python ignores PYTHONPATH/sitecustomize poisoning",
            lambda: (
                None
                if process.returncode == 0 and not sentinel.exists()
                else (_ for _ in ()).throw(RuntimeError(process.stderr or "sitecustomize executed"))
            ),
        )

        evidence_root = temp / "evidence-happy"
        evidence_root.mkdir()
        evidence_args = evidence_fixture(evidence_root)
        suite.ok("BEP with forced flags and remote_processes > 0 is accepted", lambda: guard.evidence_verify(evidence_args))
        suite.ok(
            "evidence binds workflow identity and audited workspace hashes",
            lambda: (
                None
                if (
                    json.loads(pathlib.Path(evidence_args.evidence_out).read_text())[
                        "workflow_identity"
                    ]["ref"].endswith(guard.ROUTINE_RBE_RELEASE_TAG)
                    and evidence_args.attestation_metadata[
                        "TIN2851_ACTION_REPOSITORY"
                    ]
                    == guard.CANONICAL_REPOSITORY
                    and evidence_args.attestation_metadata[
                        "TIN2851_WORKFLOW_FILE_PATH"
                    ]
                    == guard.CANONICAL_WORKFLOW
                    and "MODULE.bazel"
                    in json.loads(pathlib.Path(evidence_args.evidence_out).read_text())[
                        "audited_workspace_hashes"
                    ]
                    and "package authority"
                    in json.loads(pathlib.Path(evidence_args.evidence_out).read_text())[
                        "not_proof_of"
                    ]
                    and len(
                        json.loads(pathlib.Path(evidence_args.evidence_out).read_text())[
                            "toolchain"
                        ]["bazel"]["sha256"]
                    )
                    == 64
                )
                else (_ for _ in ()).throw(RuntimeError("evidence binding is incomplete"))
            ),
        )

        metadata_root = temp / "evidence-metadata-tamper"
        metadata_root.mkdir()
        metadata_tamper = evidence_fixture(metadata_root)
        events = bep_for(metadata_tamper)
        for event in events:
            if "buildMetadata" in event:
                event["buildMetadata"]["metadata"]["TIN2851_WORKFLOW_SHA"] = "f" * 40
        write_bep(pathlib.Path(metadata_tamper.bep), events)
        suite.rejects(
            "BEP workflow identity metadata cannot diverge from trust state",
            "build metadata differs",
            lambda: guard.evidence_verify(metadata_tamper),
        )

        audit_root = temp / "evidence-audit-tamper"
        audit_root.mkdir()
        audit_tamper = evidence_fixture(audit_root)
        audit_snapshot = json.loads(pathlib.Path(audit_tamper.snapshot).read_text())
        audit_snapshot["audited_workspace_digest"] = "0" * 64
        pathlib.Path(audit_tamper.snapshot).write_text(
            json.dumps(audit_snapshot) + "\n", encoding="utf-8"
        )
        suite.rejects(
            "audited workspace digest cannot be changed before attestation",
            "audited-workspace digest changed",
            lambda: guard.evidence_verify(audit_tamper),
        )

        cache_only_root = temp / "evidence-cache-only"
        cache_only_root.mkdir()
        cache_only = evidence_fixture(cache_only_root)
        write_bep(pathlib.Path(cache_only.bep), bep_for(cache_only, remote=0, cache_hits=9))
        suite.rejects(
            "remote cache hits cannot substitute for remote processes",
            "remote_processes must be greater than zero",
            lambda: guard.evidence_verify(cache_only),
        )

        arc_only_root = temp / "evidence-arc-local"
        arc_only_root.mkdir()
        arc_only = evidence_fixture(arc_only_root)
        write_bep(pathlib.Path(arc_only.bep), bep_for(arc_only, remote=0, local=3))
        suite.rejects(
            "ARC placement plus local execution is not RBE proof",
            "remote_processes must be greater than zero",
            lambda: guard.evidence_verify(arc_only),
        )

        fallback_root = temp / "evidence-fallback"
        fallback_root.mkdir()
        fallback = evidence_fixture(fallback_root)
        write_bep(pathlib.Path(fallback.bep), bep_for(fallback, fallback="true"))
        suite.rejects(
            "local fallback must be disabled in effective and explicit flags",
            "remote_local_fallback",
            lambda: guard.evidence_verify(fallback),
        )

        strategy_root = temp / "evidence-local-strategy"
        strategy_root.mkdir()
        strategy = evidence_fixture(strategy_root)
        write_bep(pathlib.Path(strategy.bep), bep_for(strategy, spawn="local"))
        suite.rejects(
            "spawn strategy must be forced remote",
            "spawn_strategy",
            lambda: guard.evidence_verify(strategy),
        )

        local_mixed_root = temp / "evidence-mixed-local"
        local_mixed_root.mkdir()
        local_mixed = evidence_fixture(local_mixed_root)
        write_bep(pathlib.Path(local_mixed.bep), bep_for(local_mixed, remote=2, local=1))
        suite.rejects(
            "nonzero remote count cannot hide local spawn execution",
            "contains local execution runners",
            lambda: guard.evidence_verify(local_mixed),
        )

        test_root = temp / "evidence-test-cache"
        test_root.mkdir()
        test_evidence = evidence_fixture(test_root, command="test")
        write_bep(
            pathlib.Path(test_evidence.bep),
            bep_for(test_evidence, command="test", test_cached=True),
        )
        suite.rejects(
            "cached test result cannot substitute for remote test execution",
            "remotely executed and not remotely cached",
            lambda: guard.evidence_verify(test_evidence),
        )

        trust_root = temp / "trust-happy"
        trust_root.mkdir()
        source_repo, source_commit = make_source_repo(trust_root)
        trust_workspace = make_workspace(trust_root / "workspace")
        state = trust_root / "state.json"
        with selftest_remote(source_repo):
            args = trust_args(trust_workspace, trust_root / "trusted", state, source_commit)
            suite.ok("exact action and workflow tag bind one canonical archive", lambda: guard.trust_resolve(args))
            suite.ok("stable canonical refs and helper hashes pass post-check", lambda: guard.trust_recheck(argparse.Namespace(state=str(state))))

            state_data = json.loads(state.read_text())
            archive_helper = pathlib.Path(state_data["archive_root"]) / "scripts/routine-rbe-guard.py"
            archive_helper.write_text("mutated\n", encoding="utf-8")
            suite.rejects(
                "post-scan helper-source mutation is detected",
                "trusted helper source mutated",
                lambda: guard.trust_recheck(argparse.Namespace(state=str(state))),
            )

        floating_root = temp / "trust-floating-workflow"
        floating_root.mkdir()
        floating_repo, floating_commit = make_source_repo(floating_root)
        floating_workspace = make_workspace(floating_root / "workspace")
        with selftest_remote(floating_repo):
            suite.rejects(
                "floating reusable-workflow ref is rejected",
                "exact immutable v2.x.y tag",
                lambda: guard.trust_resolve(
                    trust_args(
                        floating_workspace,
                        floating_root / "trusted",
                        floating_root / "state.json",
                        floating_commit,
                        workflow_ref="tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@refs/tags/v2",
                        job_workflow_ref="tinyland-inc/ci-templates/.github/workflows/spoke-ci.yml@refs/tags/v2",
                    )
                ),
            )
            suite.rejects(
                "floating internal action ref is rejected before trust resolution",
                "exact release tag",
                lambda: guard.trust_resolve(
                    trust_args(
                        floating_workspace,
                        floating_root / "trusted-action",
                        floating_root / "state-action.json",
                        floating_commit,
                        action_ref="v2",
                    )
                ),
            )
            suite.rejects(
                "workflow identity inputs must equal the actual job identity",
                "identity inputs differ",
                lambda: guard.trust_resolve(
                    trust_args(
                        floating_workspace,
                        floating_root / "trusted-identity",
                        floating_root / "state-identity.json",
                        floating_commit,
                        workflow_sha="f" * 40,
                    )
                ),
            )
            suite.rejects(
                "caller workflow root cannot impersonate reusable workflow root",
                "canonical reusable-workflow root",
                lambda: guard.trust_resolve(
                    trust_args(
                        floating_workspace,
                        floating_root / "trusted2",
                        floating_root / "state2.json",
                        floating_commit,
                        workflow_ref="example/consumer/.github/workflows/ci.yml@v2.99.0",
                        job_workflow_ref="example/consumer/.github/workflows/ci.yml@v2.99.0",
                    )
                ),
            )

        mismatch_root = temp / "trust-sha-mismatch"
        mismatch_root.mkdir()
        mismatch_repo, _ = make_source_repo(mismatch_root)
        mismatch_workspace = make_workspace(mismatch_root / "workspace")
        with selftest_remote(mismatch_repo):
            suite.rejects(
                "workflow SHA must equal the exact release commit",
                "must identify one commit",
                lambda: guard.trust_resolve(
                    trust_args(
                        mismatch_workspace,
                        mismatch_root / "trusted",
                        mismatch_root / "state.json",
                        "f" * 40,
                        job_workflow_sha="f" * 40,
                    )
                ),
            )

        lightweight_root = temp / "trust-lightweight"
        lightweight_root.mkdir()
        lightweight_repo, lightweight_commit = make_source_repo(
            lightweight_root, lightweight_release=True
        )
        lightweight_workspace = make_workspace(lightweight_root / "workspace")
        with selftest_remote(lightweight_repo):
            suite.rejects(
                "lightweight exact tag cannot replace canonical annotated tag object",
                "annotated tag",
                lambda: guard.trust_resolve(
                    trust_args(
                        lightweight_workspace,
                        lightweight_root / "trusted",
                        lightweight_root / "state.json",
                        lightweight_commit,
                    )
                ),
            )

        moved_root = temp / "trust-moved"
        moved_root.mkdir()
        moved_repo, moved_commit = make_source_repo(moved_root)
        moved_workspace = make_workspace(moved_root / "workspace")
        moved_state = moved_root / "state.json"
        with selftest_remote(moved_repo):
            guard.trust_resolve(
                trust_args(moved_workspace, moved_root / "trusted", moved_state, moved_commit)
            )
            write(moved_repo / "README.md", "moved\n")
            git(moved_repo, "add", "README.md")
            git(moved_repo, "commit", "-q", "-m", "move floating tag")
            git(
                moved_repo,
                "tag",
                "-f",
                "-a",
                guard.ROUTINE_RBE_RELEASE_TAG,
                "-m",
                "moved",
            )
            suite.rejects(
                "moved exact release ref is detected after source scan",
                "tag refs moved",
                lambda: guard.trust_recheck(argparse.Namespace(state=str(moved_state))),
            )

        helper_mismatch_root = temp / "trust-helper-mismatch"
        helper_mismatch_root.mkdir()
        helper_repo, helper_commit = make_source_repo(helper_mismatch_root)
        write(helper_repo / "scripts/routine-rbe-guard.py", "tampered helper\n")
        git(helper_repo, "add", "scripts/routine-rbe-guard.py")
        git(helper_repo, "commit", "-q", "-m", "tamper helper")
        helper_commit = git(helper_repo, "rev-parse", "HEAD")
        git(
            helper_repo,
            "tag",
            "-f",
            "-a",
            guard.ROUTINE_RBE_RELEASE_TAG,
            "-m",
            "tampered",
        )
        helper_workspace = make_workspace(helper_mismatch_root / "workspace")
        with selftest_remote(helper_repo):
            suite.rejects(
                "canonical archive helper mismatch is rejected",
                "do not hash-match",
                lambda: guard.trust_resolve(
                    trust_args(
                        helper_workspace,
                        helper_mismatch_root / "trusted",
                        helper_mismatch_root / "state.json",
                        helper_commit,
                    )
                ),
            )

        old_root = temp / "publication-old-release"
        old_root.mkdir()
        old_repo, _ = make_source_repo(old_root, complete=False)
        with selftest_remote(old_repo):
            suite.rejects(
                "old exact-release bytes fail the publication gate",
                "toolchain",
                lambda: guard.publication_check(argparse.Namespace()),
            )

        published_root = temp / "publication-complete"
        published_root.mkdir()
        published_repo, _ = make_source_repo(published_root)
        with selftest_remote(published_repo):
            suite.ok(
                "complete canonical exact-release archive passes offline publication fixture",
                lambda: guard.publication_check(argparse.Namespace()),
            )

        old_trusted = os.environ.get("ROUTINE_RBE_TRUSTED_ROOT")
        os.environ["ROUTINE_RBE_TRUSTED_ROOT"] = str(ROOT)
        try:
            suite.rejects(
                "local trusted-root substitution cannot bypass publication gate",
                "local trusted-root substitution is forbidden",
                lambda: guard.publication_check(argparse.Namespace()),
            )
        finally:
            if old_trusted is None:
                os.environ.pop("ROUTINE_RBE_TRUSTED_ROOT", None)
            else:
                os.environ["ROUTINE_RBE_TRUSTED_ROOT"] = old_trusted

    print()
    print(f"routine-RBE guard selftest: {suite.passed} passed, {suite.failed} failed")
    return 0 if suite.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
