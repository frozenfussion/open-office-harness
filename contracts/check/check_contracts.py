# SPDX-License-Identifier: AGPL-3.0-only
"""Validate contracts and require examples for every declared HTTP body."""

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def expand(value: Any, base: Path) -> Any:
    """Resolve only local contract references; checks never fetch remote schemas."""
    if isinstance(value, list):
        return [expand(item, base) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if ":" in reference or "#" in reference:
            raise ValueError(f"Expected a local file reference: {reference}")
        target = (base.parent / reference).resolve()
        if not target.is_relative_to(ROOT):
            raise ValueError("Reference escapes contracts directory")
        return expand(load(target), target) | expand(
            {key: item for key, item in value.items() if key != "$ref"}, base
        )
    return {key: expand(item, base) for key, item in value.items()}


def validate_example(schema: dict[str, Any], example: Any, base: Path) -> None:
    Draft202012Validator(expand(schema, base), format_checker=FormatChecker()).validate(
        example
    )


def check_contracts() -> dict[str, int]:
    schemas = sorted(ROOT.rglob("*.schema.json"))
    for path in schemas:
        schema = load(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(expand(schema, path))

    documents = {
        path.relative_to(ROOT).as_posix(): load(path)
        for path in sorted((ROOT / "http").glob("*.openapi.yaml"))
    }
    expected = set()
    for name, document in documents.items():
        validate(document)
        for path, methods in document["paths"].items():
            for method, operation in methods.items():
                assert operation["security"] == (
                    [] if path == "/health" else [{"bearerAuth": []}]
                )
                if operation.get("parameters"):
                    expected.add((name, path, method, "parameters", "parameters", None))
                for media in operation.get("requestBody", {}).get("content", {}):
                    expected.add((name, path, method, "request", media, None))
                for status, response in operation["responses"].items():
                    for media in response["content"]:
                        expected.add((name, path, method, "response", media, status))

    index = load(ROOT / "examples/index.json")["examples"]
    covered_http = set()
    covered_schemas = set()
    indexed_files = set()
    for entry in index:
        example_path = ROOT / entry["file"]
        indexed_files.add(example_path.resolve())
        example = load(example_path)
        if "schema" in entry:
            base = ROOT / entry["schema"]
            schema = load(base)
            covered_schemas.add(base)
        else:
            base = ROOT / entry["openapi"]
            operation = documents[entry["openapi"]]["paths"][entry["path"]][
                entry["method"]
            ]
            if entry["kind"] == "parameters":
                parameters = operation["parameters"]
                schema = {
                    "type": "object",
                    "properties": {p["name"]: p["schema"] for p in parameters},
                    "required": [p["name"] for p in parameters if p["required"]],
                    "additionalProperties": False,
                }
            else:
                schema = http_body_schema(operation, entry)
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
        validate_example(schema, example, base)
    assert covered_http == expected, f"Missing HTTP examples: {expected - covered_http}"
    assert covered_schemas == set(schemas), "Every schema needs an example"
    assert indexed_files == {
        path.resolve()
        for path in (ROOT / "examples").rglob("*.json")
        if path.name != "index.json"
    }, "Unindexed example"

    manifest_path = ROOT / "skills/slides/manifest.json"
    manifest = load(manifest_path)
    validate_example(
        load(ROOT / "skills/manifest.schema.json"), manifest, manifest_path
    )
    for field in ("input_schema", "output_schema"):
        assert (ROOT.parent / manifest[field]).is_file()

    topics = load(ROOT / "events/topics.yaml")
    assert topics["replication_factor"] == topics["min_insync_replicas"] == 1
    assert topics["message_key"] == "correlation_id"
    names = set()
    for topic in topics["topics"]:
        assert topic["name"] not in names
        names.add(topic["name"])
        schema_path = ROOT / topic["payload_schema"]
        assert schema_path in schemas
        assert schema_path.name == topic["event_type"] + ".schema.json"
        assert topic["writers"] and topic["readers"]
    assert manifest["topic"] in names
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
    return body["content"][entry["media_type"]]["schema"]


if __name__ == "__main__":
    print(json.dumps({"status": "passed", **check_contracts()}))
