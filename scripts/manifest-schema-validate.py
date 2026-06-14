#!/usr/bin/env python3
"""Dependency-free JSON Schema validator for the Tinyland repo manifest.

Why this exists (TIN-2109): the cache-backed enrollment gate must validate the
consumer's tinyland.repo.json against schemas/tinyland-repo-manifest.schema.json
on ANY runner, with NO network and NO third-party package. The shared
`repo-manifest-validate` action previously required either host `jsonschema` or a
working `nix develop` dev shell; on nix self-hosted cluster runners a cold
`nix develop` can fail (e.g. nix-store lock permission), which would make the
fail-closed gate fail for the WRONG reason. This validator uses only the Python
standard library.

Scope: it implements the JSON Schema 2020-12 subset actually used by the manifest
schema: type, required, properties, additionalProperties, enum, const, pattern,
minLength, minItems, uniqueItems, items, $ref (local #/$defs/...), allOf, and
if/then. `format` is accepted but not enforced (jsonschema treats most formats as
annotations by default too). It is intentionally strict: unknown schema keywords
are ignored (annotation-safe), but every constraint it does understand is
enforced. When the real `jsonschema` package is importable it is preferred (so
behavior matches the authoritative validator); this stdlib path is the fallback.

Usage:
  manifest-schema-validate.py <schema.json> <manifest.json>
Exit codes: 0 valid, 1 invalid (errors printed), 2 usage/IO error.
"""

from __future__ import annotations

import json
import re
import sys


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


def validate(instance, schema, root, path, errors) -> None:
    if "$ref" in schema:
        validate(instance, _resolve_ref(root, schema["$ref"]), root, path, errors)
        # 2020-12 allows siblings to $ref; continue checking them too.

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path or '/'}: must equal const {schema['const']!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path or '/'}: {instance!r} is not one of {schema['enum']}")

    if "type" in schema and not _type_ok(instance, schema["type"]):
        errors.append(f"{path or '/'}: is not of type {schema['type']!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path or '/'}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path or '/'}: does not match pattern {schema['pattern']!r}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path or '/'}: fewer than minItems {schema['minItems']}")
        if schema.get("uniqueItems") and len(
            {json.dumps(i, sort_keys=True) for i in instance}
        ) != len(instance):
            errors.append(f"{path or '/'}: items are not unique")
        if "items" in schema:
            for idx, item in enumerate(instance):
                validate(item, schema["items"], root, f"{path}/{idx}", errors)

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

    if "if" in schema:
        cond_errors: list[str] = []
        validate(instance, schema["if"], root, path, cond_errors)
        if not cond_errors and "then" in schema:
            validate(instance, schema["then"], root, path, errors)
        elif cond_errors and "else" in schema:
            validate(instance, schema["else"], root, path, errors)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: manifest-schema-validate.py <schema.json> <manifest.json>", file=sys.stderr)
        return 2
    schema_path, manifest_path = argv[1], argv[2]
    try:
        schema = json.loads(open(schema_path, encoding="utf-8").read())
        instance = json.loads(open(manifest_path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::cannot read schema/manifest: {exc}", file=sys.stderr)
        return 2

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
            return 1
        return 0
    except ImportError:
        pass

    errors: list[str] = []
    validate(instance, schema, schema, "", errors)
    if errors:
        for msg in errors:
            print(f"::error file={manifest_path}::{msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
