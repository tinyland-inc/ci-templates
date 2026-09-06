#!/usr/bin/env python3
"""Schema router + validator for the Tinyland repo manifest.

Real `jsonschema`, or no verdict at all.

Two responsibilities, deliberately in one file
----------------------------------------------

**1. Routing.** The estate publishes two manifest schemas — `schema_version` 1
and 2 — and the composite action used to hardcode the v1 path. A consumer that
had migrated to v2 was therefore validated against v1 and failed with a list of
`Additional properties are not allowed` plus `at /schema_version: 1 was
expected`: a diagnostic that blames the manifest for declaring the version it
actually declares, when the real fact is that the gate had no branch for it.
`SCHEMA_BY_VERSION` below is the whole mapping and it is **total** — an absent,
mistyped, or unpublished `schema_version` exits 3 naming the value it saw, and
is never silently routed to v1. (This mirrors the routing site.scaffold added in
`scripts/validate_repo_manifest.py`; the idiom is deliberately the same on both
sides so a reader of one recognises the other.)

**2. One engine.** This file used to carry a second, dependency-free validator
that implemented a *subset* of JSON Schema 2020-12 and was used whenever the
`jsonschema` package was not importable. THAT FALLBACK IS GONE (TIN-4132,
operator-ratified 2026-08-27; landed here per TIN-4192). A subset validator
pointed at a schema that asserts with keywords it does not implement returns
"valid" for manifests the authoritative validator rejects — a gate that reads
as coverage while enforcing nothing, which is worse than no gate:

  - `not` went unevaluated for months, so every prohibition passed
    unconditionally. Static spokes carrying the evicted
    `authorities.gitops_receiver` (forbidden by the authority v1 schema's
    `allOf[0].then.authorities.not.required`) validated at exit 0.
  - v2 expresses its role discipline negatively (`not` ×17, `contains` ×13,
    `anyOf` ×4). Under the subset, `allOf[5]`'s `if primary_role not in
    [...overlays...]` guard fired VACUOUSLY alongside `allOf[11]`, making
    `application-owner-overlay` and `organization-execution-overlay`
    unsatisfiable — misread as schema over-reach for weeks.

A later widening + `assert_fallback_covers()` guard made the subset honest
about which keywords it enforced, but honest-about-a-gap is still a second
engine to keep in step with the first, and the differential only ever held
because a hand-written selftest asserted it.

The subset's REASON FOR EXISTING is also dead. It guarded against a cold
`nix develop` failing on a nix-store lock (TIN-2109) — a failure class of the
shared-store host-runner generation. Current ARC pods mount per-pod ephemeral
PVC nix stores, so cross-job store-lock contention is structurally gone (GF
substrate confirmation, 2026-08-27). Supplying the dependency is the calling
workflow's job — no ci-templates composite does it, `nix-setup` and `setup-nix`
included (see MISSING_ENGINE_MESSAGE below for why that sentence used to read
otherwise). A host without it now gets a VISIBLE red naming the dependency
(exit 5) instead of a silently weaker verdict. A gate that refuses is honest; a
gate that quietly validates less is the defect this file used to be.

**3. JSON equality, not Python equality.** `_as_schema_version()` reads the
declared version by JSON's rules, not Python's: `true` is NOT version 1 even
though `bool` subclasses `int`, while `2.0` IS version 2, because JSON Schema
2020-12 counts a number with zero fractional part as an `integer` and compares
numbers mathematically. The router must agree with the schema it routes to —
exiting 3 on `2.0` would refuse to route a document that the schema it would
have routed to accepts.

Usage:
  manifest-schema-validate.py <schema.json> <manifest.json>
  manifest-schema-validate.py --schemas-dir <dir> <manifest.json>

The second form routes by the manifest's own `schema_version`; it is what the
composite action calls. The first form validates against exactly the schema
named, and is how a caller pins one on purpose (the selftest uses it to prove a
v2 manifest really is rejected by the v1 schema).

Exit codes:
  0  valid against the schema for its declared schema_version
  1  invalid against that schema
  2  usage / IO error: the CLI was called wrongly, or the manifest or a schema
     could not be read or parsed
  3  schema_version absent, mistyped, or naming no published schema
  4  the schema the manifest routes to is not present in this checkout
  5  no engine: `jsonschema` is not importable and this gate refuses to
     substitute a weaker validator

2 and 5 are DELIBERATELY DISTINCT, and were not always. The refusal used to
share exit 2 with every usage/IO error, so the composite action's `2)` arm --
written for the refusal -- told a consumer with an unparseable
`tinyland.repo.json` that "this is a RUNNER problem, not a manifest problem".
It was neither true nor actionable: the caller went looking at their runner
image for a defect that was a comma in their own file. Two meanings on one code
is how a diagnostic lies while every test still passes, so they are separated
here and each arm is asserted by the selftest.
"""

from __future__ import annotations

import json
import sys

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED_VERSION = 3
EXIT_MISSING_SCHEMA = 4
EXIT_NO_ENGINE = 5

#: The total published mapping, relative to the vendored `schemas/` directory.
#: A version absent from this dict has no schema here, and saying so is the
#: point — never fall back to v1.
SCHEMA_BY_VERSION: dict[int, str] = {
    1: "tinyland-repo-manifest.schema.json",
    2: "tinyland-repo-manifest.v2.schema.json",
}

#: Dialects seen live in the estate that satisfy no published schema. Named in
#: the failure text so an operator hitting one is told what they have.
KNOWN_UNSUPPORTED_DIALECTS = (
    'a semver string such as "1.0.0"',
    'an apiVersion/kind envelope such as "tinyland.repo/v1"',
)

#: The one diagnostic for a missing engine. Kept as a module constant because
#: the selftest greps for it: an exit code alone cannot prove the operator was
#: told WHICH dependency to provide, and "refuses loudly" is the whole claim of
#: this change.
#:
#: The remedy sentence is load-bearing and was WRONG in the first draft of this
#: change: it said "provide it via the nix-setup composite (the ci devshell
#: closure carries it)". `nix-setup` does not carry it and cannot -- grep its
#: action.yml for `python|pip|jsonschema|nix develop` and the only line that
#: matches is `set -euo pipefail`; it detects Attic and Bazel cache endpoints.
#: `setup-nix` installs Nix and starts the daemon; it installs no python
#: package either. A hard refusal whose named remedy is inert is a dead end
#: with a helpful tone, so the message now names remedies that exist and says
#: plainly which composites do not help.
MISSING_ENGINE_MESSAGE = (
    "python package 'jsonschema' is not importable, so this gate has no "
    "validator. It REFUSES to substitute a weaker one (TIN-4132: the stdlib "
    "subset it used to fall back to silently skipped `not`, `contains` and "
    "`anyOf`, and passed manifests carrying prohibited keys). Remedy: make the "
    "python3 this step runs one that CAN import it. Add a step BEFORE this one "
    "that puts it on PATH -- `nix profile install "
    "nixpkgs#python3Packages.jsonschema` -- or run the calling job inside a "
    "devshell that carries it. The ci-templates `nix-setup` and `setup-nix` "
    "composites do NOT provide it: nix-setup configures Attic/Bazel cache "
    "endpoints and setup-nix installs Nix itself, and neither installs a "
    "python package."
)


class UnsupportedSchemaVersion(Exception):
    """Raised when no vendored schema covers the declared `schema_version`."""


def _supported() -> str:
    return ", ".join(str(v) for v in sorted(SCHEMA_BY_VERSION))


def _as_schema_version(value: object) -> int | None:
    """Return the integer `schema_version` `value` denotes, or None.

    JSON's equality rules, not Python's, so the router and the schema it routes
    to cannot disagree:

    * `true` is not version 1, even though `bool` subclasses `int` in Python.
      The v1 schema pins `{"const": 1}`, and JSON Schema 2020-12 §4.2.2 makes a
      boolean and a number values of different types that are never equal.
    * `2.0` *is* version 2. JSON Schema counts a number with zero fractional
      part as an `integer` and compares numbers mathematically, so the v2
      schema's `{"const": 2}` accepts `2.0`. A router that exited 3 on `2.0`
      would be refusing to route a document the schema accepts — the gate
      contradicting itself, and the operator told to fix a conformant manifest.
    * `2.5`, `NaN`, and `inf` denote no version: `is_integer()` is false for
      all three.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def resolve_schema_name(document: object) -> str:
    """Return the vendored schema filename for `document`'s `schema_version`.

    Raises `UnsupportedSchemaVersion` — never silently defaults to v1 — when the
    document declares no version, one of a non-integer type, or an integer no
    vendored schema accepts.
    """
    if not isinstance(document, dict):
        raise UnsupportedSchemaVersion(
            f"repo manifest is not a JSON object (got {type(document).__name__}); "
            f"a Tinyland manifest is an object with schema_version {_supported()}"
        )

    if "schema_version" not in document:
        raise UnsupportedSchemaVersion(
            "manifest declares no schema_version. The gate does not assume 1: an "
            f"unversioned manifest is indistinguishable from {KNOWN_UNSUPPORTED_DIALECTS[1]}. "
            f"Declare schema_version as one of: {_supported()}."
        )

    declared = document["schema_version"]
    version = _as_schema_version(declared)

    if version is None:
        raise UnsupportedSchemaVersion(
            f"schema_version is {json.dumps(declared)} ({type(declared).__name__}), which "
            "denotes no integer version and so no vendored schema accepts it. The published "
            f"schemas pin schema_version to an integer const ({_supported()}) — a JSON number "
            "with zero fractional part such as 2.0 counts, a boolean and a string do not; "
            f"live non-conforming dialects include {' and '.join(KNOWN_UNSUPPORTED_DIALECTS)}."
        )

    try:
        return SCHEMA_BY_VERSION[version]
    except KeyError:
        raise UnsupportedSchemaVersion(
            f"schema_version {version} names no vendored schema. Supported versions: "
            f"{_supported()}. If {version} is a real new manifest revision, vendor its schema "
            "under schemas/ and add it to SCHEMA_BY_VERSION in this file — routing it to the "
            "v1 schema would report a const mismatch instead of the truth."
        ) from None


def _read_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.loads(handle.read())


def _usage() -> int:
    print(
        "usage: manifest-schema-validate.py <schema.json> <manifest.json>\n"
        "       manifest-schema-validate.py --schemas-dir <dir> <manifest.json>",
        file=sys.stderr,
    )
    return EXIT_USAGE


def main(argv: list[str]) -> int:
    routed = False
    if len(argv) == 4 and argv[1] == "--schemas-dir":
        routed = True
        schemas_dir, manifest_path = argv[2], argv[3]
        schema_path = None
    elif len(argv) == 3:
        schema_path, manifest_path = argv[1], argv[2]
    else:
        return _usage()

    # Resolve the engine BEFORE reading anything. A missing engine is not a
    # property of this manifest, and reporting it as `file=<manifest>` would
    # annotate an innocent file in the consumer's diff.
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        # EXIT_NO_ENGINE, not EXIT_USAGE. Sharing a code with "the manifest is
        # not readable" is what let the composite action attribute a malformed
        # tinyland.repo.json to the runner image.
        print(f"::error::{MISSING_ENGINE_MESSAGE}", file=sys.stderr)
        return EXIT_NO_ENGINE

    try:
        instance = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::cannot read manifest: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if routed:
        try:
            schema_name = resolve_schema_name(instance)
        except UnsupportedSchemaVersion as exc:
            print(f"::error file={manifest_path}::{exc}", file=sys.stderr)
            return EXIT_UNSUPPORTED_VERSION
        schema_path = f"{schemas_dir.rstrip('/')}/{schema_name}"
        try:
            schema = _read_json(schema_path)
        except FileNotFoundError:
            # Never "validator unavailable": the version is nominally supported
            # but factually ungated, so nothing checked this manifest.
            print(
                f"::error file={manifest_path}::schema_version "
                f"{instance['schema_version']} routes to {schema_name}, which is not present "
                f"in {schemas_dir} — the manifest was not validated against anything",
                file=sys.stderr,
            )
            return EXIT_MISSING_SCHEMA
        except (OSError, json.JSONDecodeError) as exc:
            print(f"::error::cannot read schema {schema_path}: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"::notice::repo manifest schema_version {instance['schema_version']} -> {schema_name}")
    else:
        try:
            schema = _read_json(schema_path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"::error::cannot read schema: {exc}", file=sys.stderr)
            return EXIT_USAGE

    Draft202012Validator.check_schema(schema)
    errs = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda e: list(e.absolute_path),
    )
    if errs:
        for e in errs:
            p = "/" + "/".join(str(x) for x in e.absolute_path)
            print(f"::error file={manifest_path}::at {p}: {e.message}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_VALID


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
