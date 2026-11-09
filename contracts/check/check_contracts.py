# SPDX-License-Identifier: AGPL-3.0-only
"""Validate schemas, OpenAPI contracts, examples, and topic mappings offline."""

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def expand(value: Any, base: Path) -> Any:
    """Resolve local files and JSON pointers without fetching remote schemas."""
    if isinstance(value, list):
        return [expand(item, base) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        filename, _, pointer = reference.partition("#")
        require(":" not in filename, f"Remote reference is not allowed: {reference}")
        target = (base.parent / filename).resolve() if filename else base.resolve()
        require(
            target.is_relative_to(ROOT), f"Reference escapes contracts: {reference}"
        )
        resolved = load(target)
        if pointer:
            require(pointer.startswith("/"), f"Invalid JSON pointer: {reference}")
            for part in pointer[1:].split("/"):
                key = part.replace("~1", "/").replace("~0", "~")
                try:
                    resolved = (
                        resolved[int(key)]
                        if isinstance(resolved, list)
                        else resolved[key]
                    )
                except (KeyError, IndexError, ValueError, TypeError) as exc:
                    raise ValueError(
                        f"Unresolved reference: {reference} in {base}"
                    ) from exc
        return expand(resolved, target) | expand(
            {key: item for key, item in value.items() if key != "$ref"}, base
        )
    return {key: expand(item, base) for key, item in value.items()}


def validate_example(schema: dict[str, Any], example: Any, base: Path) -> None:
    Draft202012Validator(expand(schema, base), format_checker=FormatChecker()).validate(
        example
    )


def http_cases(
    name: str, path: str, method: str, operation: dict[str, Any]
) -> set[tuple]:
    cases = set()
    if operation.get("parameters"):
        cases.add((name, path, method, "parameters", "parameters", None))
    for media in operation.get("requestBody", {}).get("content", {}):
        cases.add((name, path, method, "request", media, None))
    for status, response in operation["responses"].items():
        for media in response.get("content", {}):
            cases.add((name, path, method, "response", media, status))
    return cases


def validate_parameters(
    operation: dict[str, Any], example: Any, base: Path, path: str
) -> None:
    parameters = operation["parameters"]
    schema = {
        "type": "object",
        "properties": {p["name"]: p["schema"] for p in parameters},
        "required": [p["name"] for p in parameters if p.get("required", False)],
        "additionalProperties": False,
    }
    validate_example(schema, example, base)
    if path == "/api/models":
        require(
            example.get("purpose") != "chat" or "tier" in example,
            "Registry lookup: chat purpose requires tier",
        )
        require(
            example.get("purpose") == "chat" or "tier" not in example,
            "Registry lookup: omit tier for non-chat purposes",
        )


def check_contracts() -> dict[str, int]:
    schemas = sorted(
        path
        for folder in ("events", "skills")
        for path in (ROOT / folder).rglob("*.schema.json")
    )
    require(bool(schemas), "No JSON Schemas found")
    for path in schemas:
        schema = load(path)
        require(
            schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
            f"Expected draft 2020-12 schema: {path}",
        )
        Draft202012Validator.check_schema(expand(schema, path))

    documents = {
        path.relative_to(ROOT).as_posix(): load(path)
        for path in sorted((ROOT / "http").glob("*.openapi.yaml"))
    }
    require(len(documents) == 3, "Expected three OpenAPI documents")
    expected = set()
    for name, document in documents.items():
        validate(document)
        for path, methods in document["paths"].items():
            for method, operation in methods.items():
                require(
                    operation["security"]
                    == ([] if path == "/health" else [{"bearerAuth": []}]),
                    f"Incorrect bearer authentication: {name} {method} {path}",
                )
                expected.update(http_cases(name, path, method, operation))

    index = load(ROOT / "examples/index.json")["examples"]
    covered_http = set()
    covered_schemas = set()
    indexed_files = set()
    for entry in index:
        example_path = ROOT / entry["file"]
        require(
            example_path.resolve() not in indexed_files,
            f"Duplicate indexed example: {example_path}",
        )
        indexed_files.add(example_path.resolve())
        example = load(example_path)
        try:
            if "schema" in entry:
                base = ROOT / entry["schema"]
                validate_example(load(base), example, base)
                covered_schemas.add(base)
            else:
                base = ROOT / entry["openapi"]
                operation = documents[entry["openapi"]]["paths"][entry["path"]][
                    entry["method"]
                ]
                if entry["kind"] == "parameters":
                    validate_parameters(operation, example, base, entry["path"])
                else:
                    validate_example(http_body_schema(operation, entry), example, base)
                covered_http.add(
                    (
                        entry["openapi"],
                        entry["path"],
                        entry["method"],
                        entry["kind"],
                        entry["media_type"],
                        entry.get("status"),
                    )
                )
        except (ValueError, KeyError) as exc:
            raise ValueError(f"Invalid example {example_path}: {exc}") from exc
    require(
        covered_http == expected,
        f"HTTP coverage mismatch; missing: {expected - covered_http}; unexpected: {covered_http - expected}",
    )
    require(
        covered_schemas == set(schemas),
        f"Schema coverage mismatch: {set(schemas) ^ covered_schemas}",
    )
    actual_files = {
        path.resolve()
        for path in (ROOT / "examples").rglob("*.json")
        if path.name != "index.json"
    }
    require(
        indexed_files == actual_files,
        f"Example index mismatch: {indexed_files ^ actual_files}",
    )

    manifest_path = ROOT / "skills/slides/manifest.json"
    manifest = load(manifest_path)
    validate_example(
        load(ROOT / "skills/manifest.schema.json"), manifest, manifest_path
    )
    for field in ("input_schema", "output_schema"):
        require(
            (ROOT.parent / manifest[field]).is_file(),
            f"Manifest references missing {field}",
        )

    topics = load(ROOT / "events/topics.yaml")
    require(
        topics["replication_factor"] == topics["min_insync_replicas"] == 1,
        "Topic replication and minimum in-sync replicas must be 1",
    )
    require(
        topics["message_key"] == "correlation_id",
        "Event topic message key must be correlation_id",
    )
    names = set()
    for topic in topics["topics"]:
        name = topic["name"]
        require(name not in names, f"Duplicate topic: {name}")
        names.add(name)
        require(
            bool(topic["writers"] and topic["readers"]),
            f"Missing writers/readers: {name}",
        )
        if name == "ooh.smoke":
            require(
                topic.get("payload_schema") is None
                and topic.get("event_type") is None
                and topic.get("envelope") is False,
                "ooh.smoke must be free-form, without a schema or envelope",
            )
            continue
        schema_path = ROOT / topic["payload_schema"]
        require(
            schema_path in schemas,
            f"Missing topic payload schema: {name}: {schema_path}",
        )
        require(
            schema_path.name == topic["event_type"] + ".schema.json",
            f"Topic payload/type mismatch: {name}",
        )
    require(manifest["topic"] in names, "Slides manifest references a missing topic")
    return {
        "schemas": len(schemas),
        "openapi_documents": len(documents),
        "http_bodies": len(expected),
        "examples": len(index),
        "topics": len(names),
    }


def http_body_schema(
    operation: dict[str, Any], entry: dict[str, Any]
) -> dict[str, Any]:
    body = (
        operation["requestBody"]
        if entry["kind"] == "request"
        else operation["responses"][entry["status"]]
    )
    content = body.get("content", {})
    require(
        entry["media_type"] in content, f"No body declared for example: {entry['file']}"
    )
    return content[entry["media_type"]]["schema"]


if __name__ == "__main__":
    print(json.dumps({"status": "passed", **check_contracts()}))
