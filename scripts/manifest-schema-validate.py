#!/usr/bin/env python3
"""Validate a Tinyland repo manifest against a JSON Schema — with the real
`jsonschema` library, or not at all.

THE STDLIB FALLBACK IS GONE, DELIBERATELY (TIN-4132, operator-ratified
2026-08-27). It implemented `$ref, const, enum, type, minLength, pattern,
minItems, uniqueItems, items, required, additionalProperties, allOf, if/then`
and silently ignored everything else as "annotation-safe". That made it a
gate-that-looks-like-coverage one layer below the schema fork this repo
already repaired once:

  - `not` was never evaluated, so every prohibition passed unconditionally.
    Three static spokes carrying the evicted `authorities.gitops_receiver`
    (forbidden by v1's allOf[0].then.authorities.not.required) validated at
    rc=0 against BOTH v1 forks.
  - v2 expresses its role discipline as negative branches (`not` x17,
    `contains` x13, `anyOf` x4, `if` x20). Under the fallback, allOf[5]'s
    `if primary_role not in [...overlays...]` guard fired VACUOUSLY alongside
    allOf[11], making application-owner-overlay and
    organization-execution-overlay literally unsatisfiable -- which was
    misread as schema over-reach for weeks.

The fallback's reason for existing is dead. It guarded against cold
`nix develop` failures on nix-store locks (TIN-2109) -- a failure class of the
shared-store host-runner generation. Current ARC pods mount per-pod ephemeral
PVC nix stores, so cross-job store-lock contention is structurally gone
(GF substrate confirmation, 2026-08-27). The dependency is now guaranteed by
the `nix-setup` composite (cache-hot from the in-cluster Attic), and a host
without `jsonschema` gets a visible red naming the dependency instead of a
silently weaker validation. A gate that crashes is honest; a gate that
quietly validates less is the defect this file used to be.
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: manifest-schema-validate.py <schema.json> <manifest.json>", file=sys.stderr)
        return 2
    schema_path, manifest_path = argv[1], argv[2]

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print(
            "::error::python package 'jsonschema' is not importable. This gate "
            "REFUSES to fall back to a weaker validator (TIN-4132: the old "
            "stdlib fallback silently skipped `not`/`contains`/`anyOf` and "
            "passed real violations). Provide jsonschema via the nix-setup "
            "composite (the ci devshell closure carries it) or the host "
            "python environment, then re-run.",
            file=sys.stderr,
        )
        return 2

    try:
        schema = json.loads(open(schema_path, encoding="utf-8").read())
        instance = json.loads(open(manifest_path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::cannot read schema/manifest: {exc}", file=sys.stderr)
        return 2

    Draft202012Validator.check_schema(schema)
    errs = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda e: list(e.absolute_path),
    )
    if errs:
        for e in errs:
            p = "/" + "/".join(str(x) for x in e.absolute_path)
            print(f"::error file={manifest_path}::at {p}: {e.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
