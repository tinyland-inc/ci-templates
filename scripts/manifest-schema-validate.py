#!/usr/bin/env python3
"""Dependency-free JSON Schema validator + schema router for the Tinyland repo manifest.

Why this exists (TIN-2109): the cache-backed enrollment gate must validate the
consumer's tinyland.repo.json against a vendored schema under `schemas/` on ANY
runner, with NO network and NO third-party package. The shared
`repo-manifest-validate` action previously required either host `jsonschema` or a
working `nix develop` dev shell; on nix self-hosted cluster runners a cold
`nix develop` can fail (e.g. nix-store lock permission), which would make the
fail-closed gate fail for the WRONG reason. This validator uses only the Python
standard library.

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

**2. Honest fallback coverage.** The stdlib path implements a *subset* of JSON
Schema 2020-12. A subset validator pointed at a schema that uses keywords it
does not implement returns "valid" for manifests the authoritative validator
would reject — a gate that reads as coverage while enforcing nothing, which is
worse than no gate. The v2 schema uses `not`, `anyOf`, and `contains` heavily
(17/4/13 occurrences), none of which the original subset understood. So the
subset is widened to cover them, AND `assert_fallback_covers()` walks the schema
and refuses to run at all (exit 2) if it meets an assertion keyword outside
`ENFORCED_KEYWORDS`. A future schema keyword now stops the gate loudly instead
of quietly draining it.

When the real `jsonschema` package is importable it is preferred (so behavior
matches the authoritative validator) and the coverage guard is skipped — it has
nothing to guard.

Usage:
  manifest-schema-validate.py <schema.json> <manifest.json>
  manifest-schema-validate.py --schemas-dir <dir> <manifest.json>

The second form routes by the manifest's own `schema_version`; it is what the
composite action calls. The first form validates against exactly the schema
named, and is how a caller pins one on purpose (the Justfile self-test uses it
to prove a v2 manifest really is rejected by the v1 schema).

**3. JSON equality, not Python equality.** The subset compares `const`/`enum`
with `_json_equal()`, not `==`/`in`. Python's `==` is the wrong relation for
JSON values in two directions at once: `True == 1` is true in Python and false
in JSON (a boolean and a number are different types and never equal), while
`1 == 1.0` is true in both — JSON Schema compares numbers mathematically. Using
`==` therefore let a JSON `true` satisfy `{"const": 1}`, which is exactly the
`schema_version` const the v1 schema pins. `_as_schema_version()` applies the
same rules to the router, so `2.0` routes to v2 rather than being rejected by a
gate whose own schema would have accepted it.

Exit codes:
  0  valid against the schema for its declared schema_version
  1  invalid against that schema
  2  usage / IO error, or the stdlib fallback cannot faithfully evaluate the schema
  3  schema_version absent, mistyped, or naming no published schema
  4  the schema the manifest routes to is not present in this checkout
"""

from __future__ import annotations

import json
import re
import sys

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED_VERSION = 3
EXIT_MISSING_SCHEMA = 4

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

#: Assertion keywords the stdlib fallback actually enforces. The coverage guard
#: below refuses any schema that asserts with something outside this set, so the
#: subset can never silently under-validate.
ENFORCED_KEYWORDS = frozenset(
    {
        "$ref",
        "const",
        "enum",
        "type",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "items",
        "contains",
        "properties",
        "required",
        "additionalProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
    }
)

#: Keywords that carry no assertion. Ignoring them is correct, not a gap.
#: `format` is an annotation by default in 2020-12, which is also how the
#: authoritative validator treats it unless a format checker is wired in.
ANNOTATION_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$anchor",
        "$comment",
        "$defs",
        "definitions",
        "title",
        "description",
        "default",
        "examples",
        "format",
        "deprecated",
        "readOnly",
        "writeOnly",
    }
)

#: Where subschemas live, so the coverage walk visits schema positions only and
#: never mistakes a user-chosen property NAME (`owns_auth`, `apply_plane`) for a
#: keyword.
_SUBSCHEMA_KEYS = ("additionalProperties", "items", "contains", "not", "if", "then", "else")
_SUBSCHEMA_LIST_KEYS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SUBSCHEMA_MAP_KEYS = ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas")


class UnsupportedSchemaVersion(Exception):
    """Raised when no vendored schema covers the declared `schema_version`."""


class FallbackCoverageGap(Exception):
    """Raised when the stdlib subset cannot faithfully evaluate a schema."""


def _supported() -> str:
    return ", ".join(str(v) for v in sorted(SCHEMA_BY_VERSION))


def _json_equal(left, right) -> bool:
    """JSON Schema value equality (2020-12 §4.2.2), which Python `==` is not.

    Two divergences matter here, and they point in opposite directions:

    * `bool` subclasses `int` in Python, so `True == 1` and `False == 0`. In
      JSON a boolean and a number are values of different types and are never
      equal. With bare `==`, `{"const": 1}` — the `schema_version` const the v1
      manifest schema pins — accepts the document `{"schema_version": true}`.
    * Numbers, on the other hand, *do* compare mathematically: `1` and `1.0`
      are the same JSON value, so an integral float must satisfy an integer
      `const`/`enum`. A naive "the types must match exactly" repair would break
      that and disagree with the authoritative validator the other way.

    Everything else is structural: same type, and for arrays/objects the same
    shape compared elementwise with these same rules.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(value, right[key]) for key, value in left.items()
        )
    return False


def _as_schema_version(value: object) -> int | None:
    """Return the integer `schema_version` `value` denotes, or None.

    The same JSON equality rules `_json_equal` applies, applied to routing, so
    the router and the schema it routes to cannot disagree:

    * `true` is not version 1, even though `bool` subclasses `int` in Python.
    * `2.0` *is* version 2. JSON Schema 2020-12 counts a number with zero
      fractional part as an `integer`, and compares numbers mathematically, so
      the v2 schema's `{"const": 2}` accepts `2.0`. A router that exited 3 on
      `2.0` would be refusing to route a document the schema it would have
      routed to accepts — the gate contradicting itself, and the operator told
      to fix a manifest that is in fact conformant.
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


def assert_fallback_covers(schema, root=None, path="#") -> None:
    """Refuse to evaluate a schema whose assertions the subset does not implement.

    Walks schema POSITIONS only. A validator that ignores `not`/`anyOf`/
    `contains` reports a manifest valid that the authoritative validator
    rejects, and the caller cannot tell the difference from a real pass.
    """
    if isinstance(schema, bool) or schema is None:
        return
    if not isinstance(schema, dict):
        raise FallbackCoverageGap(f"{path}: schema node is not an object or boolean")

    for key in schema:
        if key in ENFORCED_KEYWORDS or key in ANNOTATION_KEYWORDS:
            continue
        raise FallbackCoverageGap(
            f"{path}: schema uses '{key}', which the dependency-free fallback validator does "
            f"not enforce. Refusing to report a verdict it cannot back: install `jsonschema` "
            f"on this runner, or implement '{key}' in scripts/manifest-schema-validate.py and "
            "add it to ENFORCED_KEYWORDS."
        )

    for key in _SUBSCHEMA_KEYS:
        if key in schema:
            assert_fallback_covers(schema[key], root, f"{path}/{key}")
    for key in _SUBSCHEMA_LIST_KEYS:
        for idx, sub in enumerate(schema.get(key, []) or []):
            assert_fallback_covers(sub, root, f"{path}/{key}/{idx}")
    for key in _SUBSCHEMA_MAP_KEYS:
        for name, sub in (schema.get(key) or {}).items():
            assert_fallback_covers(sub, root, f"{path}/{key}/{name}")


def _type_ok(value, expected) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, t) for t in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _resolve_ref(root: dict, ref: str):
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref (only local refs): {ref}")
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def _fails(instance, schema, root) -> bool:
    """True when `instance` violates `schema`. Used by not/anyOf/oneOf/contains."""
    probe: list[str] = []
    validate(instance, schema, root, "", probe)
    return bool(probe)


def validate(instance, schema, root, path, errors) -> None:
    if isinstance(schema, bool):
        if not schema:
            errors.append(f"{path or '/'}: schema is `false`; no value is valid here")
        return

    if "$ref" in schema:
        validate(instance, _resolve_ref(root, schema["$ref"]), root, path, errors)
        # 2020-12 allows siblings to $ref; continue checking them too.

    # `_json_equal`, never `!=`/`not in`: Python would accept `true` for
    # `{"const": 1}` (bool subclasses int) while still needing 1.0 to satisfy 1.
    if "const" in schema and not _json_equal(instance, schema["const"]):
        errors.append(
            f"{path or '/'}: must equal const {json.dumps(schema['const'])}, "
            f"got {json.dumps(instance)}"
        )

    if "enum" in schema and not any(
        _json_equal(instance, option) for option in schema["enum"]
    ):
        errors.append(
            f"{path or '/'}: {json.dumps(instance)} is not one of "
            f"{json.dumps(schema['enum'])}"
        )

    if "type" in schema and not _type_ok(instance, schema["type"]):
        errors.append(f"{path or '/'}: is not of type {schema['type']!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path or '/'}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path or '/'}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path or '/'}: does not match pattern {schema['pattern']!r}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path or '/'}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path or '/'}: more than maxItems {schema['maxItems']}")
        if schema.get("uniqueItems") and len(
            {json.dumps(i, sort_keys=True) for i in instance}
        ) != len(instance):
            errors.append(f"{path or '/'}: items are not unique")
        if "items" in schema:
            for idx, item in enumerate(instance):
                validate(item, schema["items"], root, f"{path}/{idx}", errors)
        if "contains" in schema and not any(
            not _fails(item, schema["contains"], root) for item in instance
        ):
            errors.append(f"{path or '/'}: no item satisfies `contains`")

    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path or '/'}: missing required property '{key}'")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path or '/'}: additional property '{key}' is not allowed")
        for key, subschema in props.items():
            if key in instance:
                validate(instance[key], subschema, root, f"{path}/{key}", errors)

    for sub in schema.get("allOf", []):
        validate(instance, sub, root, path, errors)

    if "anyOf" in schema and all(_fails(instance, sub, root) for sub in schema["anyOf"]):
        errors.append(f"{path or '/'}: matches none of the {len(schema['anyOf'])} `anyOf` branches")

    if "oneOf" in schema:
        matched = sum(1 for sub in schema["oneOf"] if not _fails(instance, sub, root))
        if matched != 1:
            errors.append(f"{path or '/'}: matches {matched} `oneOf` branches, expected exactly 1")

    if "not" in schema and not _fails(instance, schema["not"], root):
        errors.append(f"{path or '/'}: must NOT match the `not` subschema, but does")

    if "if" in schema:
        if not _fails(instance, schema["if"], root):
            if "then" in schema:
                validate(instance, schema["then"], root, path, errors)
        elif "else" in schema:
            validate(instance, schema["else"], root, path, errors)


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

    # Prefer the authoritative validator when available.
    try:
        from jsonschema import Draft202012Validator

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
    except ImportError:
        pass

    try:
        assert_fallback_covers(schema)
    except FallbackCoverageGap as exc:
        print(f"::error file={schema_path}::{exc}", file=sys.stderr)
        return EXIT_USAGE

    errors: list[str] = []
    validate(instance, schema, schema, "", errors)
    if errors:
        for msg in errors:
            print(f"::error file={manifest_path}::{msg}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_VALID


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
