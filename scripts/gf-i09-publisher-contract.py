"""Mutation-resistant contract for the GF-I09 reusable publisher."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

WORKFLOW = Path(".github/workflows/gf-i09-release-publisher.yml")
EXPECTED_USES = Counter(
    {
        "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10": 1,
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a": 1,
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c": 2,
        "oras-project/setup-oras@1d808f7d7f6995cc68b7bf507bfe5c5446e1dc9d": 2,
        "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6": 2,
    }
)
EXPECTED_PERMISSIONS = {
    "prepare": {"contents": "read"},
    "publish": {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
        "packages": "write",
    },
    "verify": {"actions": "read", "contents": "read", "packages": "read"},
    "result": {"contents": "read"},
}
REQUIRED = (
    'test "${GITHUB_EVENT_NAME}" = "push"',
    'test "${REF_PROTECTED}" = "true"',
    ".commit.verification.verified == true",
    ".commit.verification.reason == \"valid\"",
    "git\", \"ls-files\", \"--stage\"",
    "GF Canonical JSON v1",
    "PREREQUISITES = (",
    "EVIDENCE = (",
    "job_workflow_ref",
    "job_workflow_sha",
    "certificate_identity",
    "workflow_source_sha256",
    "cosign sign-blob",
    "absent()",
    "oras manifest fetch",
    "oras pull --output",
    "cosign verify-blob",
    "publication-receipt.json",
    "Threat boundary: the verified protected caller commit is the trusted producer.",
    "candidate bytes changed after the trusted gate",
    "downloaded payload differs from trusted prepare output",
    "downloaded statement differs from trusted prepare output",
    "frozen statement does not derive from the trusted gate candidate",
    "Emit only independently verified truth",
)
FORBIDDEN = (
    "repository_dispatch",
    "workflow_dispatch",
    "kubectl ",
    "terraform ",
    "tofu ",
    "opentofu ",
    "GF_I09_HANDOFF",
    "GITHUB_ENV",
)


def blocks(source: str) -> dict[str, str]:
    if "\njobs:\n" not in source:
        return {}
    body = source.split("\njobs:\n", 1)[1]
    matches = list(re.finditer(r"(?m)^  ([a-z][a-z0-9_-]*):\n", body))
    return {
        match.group(1): body[
            match.start() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(body)
        ]
        for index, match in enumerate(matches)
    }


def permission_map(block: str) -> dict[str, str] | None:
    match = re.search(r"(?m)^    permissions:\n((?:      [a-z-]+: [a-z]+\n)+)", block)
    if not match:
        return None
    result = {}
    for line in match.group(1).splitlines():
        key, value = line.strip().split(": ", 1)
        result[key] = value
    return result


def verdict(source: str) -> list[str]:
    errors: list[str] = []
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    header = source.split("\njobs:\n", 1)[0]
    require(
        re.search(r"(?m)^on:\n  workflow_call:\n    outputs:\n", header) is not None,
        "workflow must be reusable and output-only",
    )
    require(
        re.search(r"(?m)^    (inputs|secrets):", header) is None,
        "workflow_call may accept no input or secret seam",
    )
    require(
        re.search(
            r"(?m)^  (push|pull_request|schedule|workflow_dispatch):", header
        )
        is None,
        "reusable publisher must not schedule itself",
    )

    jobs = blocks(source)
    require(
        set(jobs) == {"prepare", "publish", "verify", "result"},
        f"job census changed: {sorted(jobs)}",
    )
    for name, expected in EXPECTED_PERMISSIONS.items():
        require(
            permission_map(jobs.get(name, "")) == expected,
            f"{name} permissions must be exactly {expected}",
        )
        require(
            jobs.get(name, "").count("runs-on: tinyland-nix") == 1,
            f"{name} must use the one finite Tinyland runner class",
        )

    require(
        executable.count("id-token: write") == 1,
        "OIDC authority must exist only in publish",
    )
    require(
        executable.count("packages: write") == 1,
        "package-write authority must exist only in publish",
    )
    require(
        "actions/checkout@" not in jobs.get("publish", "")
        and "actions/checkout@" not in jobs.get("verify", ""),
        "publish and verify must never checkout caller code",
    )
    for name in ("publish", "verify", "result"):
        block = jobs.get(name, "")
        require(
            "nix develop" not in block and " just " not in block,
            f"{name} must execute no caller recipe",
        )
        require(
            "${{ inputs." not in block and "run: ${{" not in block,
            f"{name} contains a caller-controlled command",
        )
    require(
        jobs.get("prepare", "").count(
            "run: nix develop . --command just gf-i09-publisher-check"
        )
        == 1,
        "fixed check recipe must run exactly once",
    )
    require(
        jobs.get("prepare", "").count(
            "run: nix develop . --command just gf-i09-publisher-assemble"
        )
        == 1,
        "fixed assemble recipe must run exactly once",
    )

    uses = Counter(
        f"{action}@{ref}"
        for action, ref in re.findall(
            r"(?m)^\s+uses: ([^@\s]+)@([^\s#]+)", executable
        )
    )
    require(uses == EXPECTED_USES, f"action pin census changed: {uses}")
    require(
        all(
            re.fullmatch(r"[0-9a-f]{40}", item.split("@", 1)[1])
            for item in uses
        ),
        "every action must use a full immutable commit",
    )

    require(
        "value: ${{ jobs.result.outputs.published }}" in header,
        "published output must come only from result",
    )
    require(
        "VERIFIED: ${{ needs.verify.outputs.published }}" in jobs.get("result", ""),
        "result must consume verify output",
    )
    require(
        'test "${VERIFIED}" = true' in jobs.get("result", ""),
        "result must require verified=true",
    )
    require(
        "if: needs.prepare.outputs.activation_enabled == 'true'"
        in jobs.get("publish", ""),
        "publisher must be unreachable when disabled",
    )
    require(
        "if: needs.publish.result == 'success'" in jobs.get("verify", ""),
        "readback must require publication success",
    )
    require(
        jobs.get("prepare", "").count(
            ".commit.verification.verified == true"
        ) == 1
        and jobs.get("prepare", "").count(
            '.commit.verification.reason == "valid"'
        ) == 1,
        "prepare must prove the exact caller commit signature",
    )
    require(
        'called_sha = claims.get("job_workflow_sha")'
        in jobs.get("publish", ""),
        "publisher must bind the immutable called-workflow SHA claim",
    )
    require(
        executable.count(
            'runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)'
        ) == 2,
        "gate and freeze must derive the fixed handoff path independently",
    )
    require(
        executable.count("def strict_census(directory, expected):") == 3,
        "freeze, publisher, and verifier must each define strict census",
    )
    require(
        executable.count(
            'strict_census(handoff, {"payload.json", "statement-candidate.json"})'
        ) == 1
        and executable.count(
            'strict_census(publish_dir, {"payload.json", "statement-candidate.json"})'
        ) == 1
        and executable.count(
            'strict_census(original, {"payload.json", "statement-candidate.json"})'
        ) == 1,
        "all three handoff boundaries must require the exact two-entry census",
    )
    require(
        executable.count(
            "if len(entries) != len(expected) or {entry.name for entry in entries} != expected:"
        ) == 3,
        "every census must reject missing and extra entries",
    )
    require(
        executable.count(
            "if stat.S_ISLNK(entry_meta.st_mode) or not stat.S_ISREG(entry_meta.st_mode):"
        ) == 3,
        "every census must reject nested directories and symlinks",
    )
    require(
        executable.count(
            'output.write(f"candidate_digest={digest(candidate_bytes)}\\n")'
        ) == 1
        and executable.count(
            'if digest(candidate_bytes) != os.environ["CANDIDATE_DIGEST"]:'
        ) == 1
        and executable.count(
            'if digest(canonical(gate_candidate)) != os.environ["CANDIDATE_DIGEST"]:'
        ) == 2,
        "candidate bytes must remain bound through freeze, publish, and verify",
    )
    require(
        executable.count(
            'output.write(f"payload_digest={digest(frozen_payload)}\\n")'
        ) == 1
        and executable.count(
            'output.write(f"statement_digest={digest(frozen_statement)}\\n")'
        ) == 1,
        "freeze must emit trusted payload and final-statement digests",
    )
    require(
        executable.count(
            'if digest(payload_bytes) != os.environ["PREPARE_PAYLOAD_DIGEST"]:'
        ) == 2
        and executable.count(
            'if digest(statement_bytes) != os.environ["PREPARE_STATEMENT_DIGEST"]:'
        ) == 2,
        "publisher and verifier must bind downloaded constituent bytes",
    )
    require(
        executable.count(".id == $id") == 2
        and executable.count(".name == $name") == 2
        and executable.count(".digest == $digest") == 2
        and executable.count(".workflow_run.id == $run_id") == 2,
        "publisher and verifier must bind artifact identity, name, digest, and run metadata",
    )
    require(
        jobs.get("prepare", "").count(
            "candidate_digest: ${{ steps.gate.outputs.candidate_digest }}"
        ) == 1
        and jobs.get("prepare", "").count(
            "payload_digest: ${{ steps.freeze.outputs.payload_digest }}"
        ) == 1
        and jobs.get("prepare", "").count(
            "statement_digest: ${{ steps.freeze.outputs.statement_digest }}"
        ) == 1,
        "prepare must expose only trusted gate/freeze digest outputs",
    )
    require(
        len(re.findall(r"(?m)^\s+oras pull --output", executable)) == 2,
        "verify must perform exactly two immutable OCI pulls",
    )
    require(
        executable.count("cosign verify-blob") == 2,
        "verify must check both exact signed blobs",
    )

    for marker in REQUIRED:
        require(marker in source, f"required marker missing: {marker}")
    for marker in FORBIDDEN:
        require(marker not in executable, f"forbidden behavior appeared: {marker}")
    require(
        "${{ secrets." not in executable
        and re.search(r"(?m)^\s+secrets:", executable) is None,
        "workflow must not accept or read secrets",
    )
    require("runs-on: ${{" not in executable, "runner class must not be data")
    require("runner_class" not in executable, "runner-class input is forbidden")
    return errors


def self_test(source: str) -> int:
    initial = verdict(source)
    if initial:
        print("baseline GF-I09 workflow is invalid:", file=sys.stderr)
        for error in initial:
            print(f"- {error}", file=sys.stderr)
        return 1

    mutations = {
        "self scheduling": source.replace(
            "  workflow_call:\n", "  workflow_dispatch:\n  workflow_call:\n", 1
        ),
        "force input": source.replace(
            "  workflow_call:\n    outputs:\n",
            "  workflow_call:\n    inputs:\n      force:\n"
            "        type: boolean\n        default: false\n    outputs:\n",
            1,
        ),
        "arbitrary runner": source.replace(
            "runs-on: tinyland-nix", "runs-on: evil", 1
        ),
        "prepare OIDC": source.replace(
            "    permissions:\n      contents: read\n",
            "    permissions:\n      contents: read\n      id-token: write\n",
            1,
        ),
        "prepare package write": source.replace(
            "    permissions:\n      contents: read\n",
            "    permissions:\n      contents: read\n      packages: write\n",
            1,
        ),
        "mutable action": source.replace(
            "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10",
            "actions/checkout@main",
            1,
        ),
        "caller checkout in publisher": source.replace(
            "    steps:\n      - name: Install pinned ORAS\n",
            "    steps:\n"
            "      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10\n"
            "      - name: Install pinned ORAS\n",
            1,
        ),
        "raw command input": source.replace(
            "run: nix develop . --command just gf-i09-publisher-check",
            "run: ${{ inputs.command }}",
            1,
        ),
        "unsigned caller": source.replace(
            ".commit.verification.verified == true",
            ".commit.verification.verified != null",
            1,
        ),
        "called identity dropped": source.replace(
            "job_workflow_sha", "called_sha", 1
        ),
        "readback dropped": source.replace(
            'oras pull --output "${root}/receipt"',
            'true # oras pull --output "${root}/receipt"',
            1,
        ),
        "signature verify dropped": source.replace(
            "cosign verify-blob", "cosign version", 1
        ),
        "writer output": source.replace(
            "value: ${{ jobs.result.outputs.published }}",
            "value: ${{ jobs.publish.outputs.published }}",
            1,
        ),
        "candidate digest check removed": source.replace(
            'if digest(candidate_bytes) != os.environ["CANDIDATE_DIGEST"]:',
            "if False:",
            1,
        ),
        "handoff path exported": source.replace(
            "set -euo pipefail\n",
            "set -euo pipefail\n"
            '          echo "GF_I09_HANDOFF=${RUNNER_TEMP}/gf-i09-handoff" '
            '>> "${GITHUB_ENV}"\n',
            1,
        ),
        "handoff path rebound": source.replace(
            'runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)',
            'runner_temp = Path(os.environ["GF_I09_HANDOFF"]).resolve(strict=True)',
            1,
        ),
        "extra handoff entry allowed": source.replace(
            '{"payload.json", "statement-candidate.json"}',
            '{"payload.json", "statement-candidate.json", "extra"}',
            1,
        ),
        "nested handoff entry allowed": source.replace(
            "if stat.S_ISLNK(entry_meta.st_mode) or not stat.S_ISREG(entry_meta.st_mode):",
            "if stat.S_ISLNK(entry_meta.st_mode) and not stat.S_ISREG(entry_meta.st_mode):",
            1,
        ),
        "symlink handoff entry allowed": source.replace(
            "if stat.S_ISLNK(entry_meta.st_mode) or not stat.S_ISREG(entry_meta.st_mode):",
            "if not (stat.S_ISREG(entry_meta.st_mode) or stat.S_ISLNK(entry_meta.st_mode)):",
            1,
        ),
        "strict census call removed": source.replace(
            'strict_census(handoff, {"payload.json", "statement-candidate.json"})',
            "pass  # handoff census removed",
            1,
        ),
        "artifact digest check removed": source.replace(
            ".digest == $digest",
            ".digest != null",
            1,
        ),
        "artifact run binding removed": source.replace(
            ".workflow_run.id == $run_id",
            ".workflow_run != null",
            1,
        ),
        "payload constituent digest removed": source.replace(
            'if digest(payload_bytes) != os.environ["PREPARE_PAYLOAD_DIGEST"]:',
            "if False:",
            1,
        ),
        "statement constituent digest removed": source.replace(
            'if digest(statement_bytes) != os.environ["PREPARE_STATEMENT_DIGEST"]:',
            "if False:",
            1,
        ),
        "apply behavior": source.replace(
            "set -euo pipefail\n",
            "set -euo pipefail\n          kubectl apply -f release.yaml\n",
            1,
        ),
    }
    failures = []
    for name, mutated in mutations.items():
        if mutated == source:
            failures.append(f"{name}: mutation did not alter source")
        elif not verdict(mutated):
            failures.append(f"{name}: checker accepted mutation")
    if failures:
        print("GF-I09 mutation self-test FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"GF-I09 mutation self-test passed ({len(mutations)} hostile cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not WORKFLOW.is_file():
        print(f"{WORKFLOW}: missing", file=sys.stderr)
        return 1
    source = WORKFLOW.read_text(encoding="utf-8")
    if args.self_test:
        return self_test(source)
    errors = verdict(source)
    if errors:
        for error in errors:
            print(f"{WORKFLOW}: {error}", file=sys.stderr)
        return 1
    print("GF-I09 reusable publisher contract holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
