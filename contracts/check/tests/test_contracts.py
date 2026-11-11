# SPDX-License-Identifier: AGPL-3.0-only
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_contracts import ROOT, check_contracts, load, validate_example


def test_all_contracts() -> None:
    assert check_contracts()["topics"] == 13
    for document, route, field in [
        ("control-centre", "/api/models", "endpoint_url"),
        ("harness-api", "/api/files/{key}", "url"),
    ]:
        path = ROOT / f"http/{document}.openapi.yaml"
        schema = load(path)["paths"][route]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        properties = (
            schema["items"]["properties"]
            if document == "control-centre"
            else schema["properties"]
        )
        for invalid in ["not-a-uri", "https://", "https://bad host/file", "/relative"]:
            with pytest.raises(ValidationError):
                validate_example(properties[field], invalid, path)
        validate_example(
            properties[field], "https://example.invalid/path?key=value", path
        )


def test_invalid_example_is_rejected() -> None:
    path = ROOT / "events/envelope.schema.json"
    example = load(ROOT / "examples/events/envelope.example.json")
    example["payload"] = {"skill": "slides", "input": {}}
    with pytest.raises(ValidationError):
        validate_example(load(path), example, path)


@pytest.mark.parametrize("skill", ["slides", "report", "animated-deck"])
def test_generic_skill_request(skill: str) -> None:
    path = ROOT / "events/payloads/skill.requested.schema.json"
    validate_example(
        load(path),
        {
            "skill": skill,
            "skill_version": "1.2.3-beta.1",
            "input": {"custom_field": True},
        },
        path,
    )


@pytest.mark.parametrize(
    "change", [{"skill": "Bad_Name"}, {"skill_version": "1.0"}, {"input": []}]
)
def test_generic_skill_request_rejects_invalid_fields(change: dict) -> None:
    path = ROOT / "events/payloads/skill.requested.schema.json"
    value = {"skill": "report", "skill_version": "1.0.0", "input": {}} | change
    with pytest.raises(ValidationError):
        validate_example(load(path), value, path)


@pytest.mark.parametrize("failed", [False, True])
def test_generic_result_and_job_updates(failed: bool) -> None:
    output = (
        None
        if failed
        else {
            "file_key": "outputs/report/example/report.txt",
            "mime": "text/plain",
            "summary": "Synthetic report",
        }
    )
    error = {"code": "failed", "message": "Synthetic failure"} if failed else None
    result = {
        "skill": "report",
        "status": "failed" if failed else "completed",
        "output": output,
        "error": error,
    }
    path = ROOT / "events/payloads/skill.result.schema.json"
    validate_example(load(path), result, path)
    with pytest.raises(ValidationError):
        validate_example(
            load(path), result | {"status": "completed" if failed else "failed"}, path
        )
    with pytest.raises(ValidationError):
        validate_example(
            load(path),
            result
            | {
                "error": {"code": "failed", "message": "Failure"},
                "output": {
                    "file_key": "example",
                    "mime": "text/plain",
                    "summary": "Example",
                },
            },
            path,
        )
    path = ROOT / "http/harness-api.openapi.yaml"
    schema = load(path)["paths"]["/api/events"]["get"]["responses"]["200"]["content"][
        "text/event-stream"
    ]["schema"]
    result["type"] = "job." + result.pop("status")
    result["correlation_id"] = "00000000-0000-4000-8000-000000000001"
    validate_example(schema, result, path)
    with pytest.raises(ValidationError):
        validate_example(
            schema, result | {"type": "job.completed" if failed else "job.failed"}, path
        )
    for state in ("job.queued", "job.awaiting_approval"):
        validate_example(
            schema, result | {"type": state, "output": None, "error": None}, path
        )
        with pytest.raises(ValidationError):
            validate_example(schema, result | {"type": state}, path)


@pytest.mark.parametrize(
    "parameters",
    [
        {"purpose": "chat", "tier": 1},
        {"purpose": "classification"},
        {"purpose": "image"},
    ],
)
def test_registry_query(parameters: dict) -> None:
    from check_contracts import validate_parameters

    path = ROOT / "http/control-centre.openapi.yaml"
    operation = load(path)["paths"]["/api/models"]["get"]
    validate_parameters(operation, parameters, path, "/api/models")


@pytest.mark.parametrize(
    "parameters", [{"purpose": "chat"}, {"purpose": "image", "tier": 1}]
)
def test_registry_query_rejects_incorrect_tier(parameters: dict) -> None:
    from check_contracts import validate_parameters

    path = ROOT / "http/control-centre.openapi.yaml"
    operation = load(path)["paths"]["/api/models"]["get"]
    with pytest.raises(ValueError, match="tier"):
        validate_parameters(operation, parameters, path, "/api/models")


def test_component_error_reference() -> None:
    path = ROOT / "http/harness-api.openapi.yaml"
    schema = {"$ref": "#/components/schemas/Error"}
    validate_example(schema, {"code": "not_found", "message": "Missing"}, path)
    with pytest.raises(ValidationError):
        validate_example(schema, {"code": "not_found"}, path)


def test_bodyless_response_needs_no_example(monkeypatch: pytest.MonkeyPatch) -> None:
    import check_contracts as checker

    original_load = checker.load

    def load_with_bodyless_response(path: Path) -> dict:
        document = original_load(path)
        if path.name == "harness-api.openapi.yaml":
            document["paths"]["/api/uploads"]["post"]["responses"]["204"] = {
                "description": "No content"
            }
        return document

    monkeypatch.setattr(checker, "load", load_with_bodyless_response)
    checker.check_contracts()
