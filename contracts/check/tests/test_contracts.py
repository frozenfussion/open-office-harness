# SPDX-License-Identifier: AGPL-3.0-only
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_contracts import ROOT, check_contracts, load, validate_example


def test_all_contracts() -> None:
    assert check_contracts()["topics"] == 11


def test_invalid_example_is_rejected() -> None:
    path = ROOT / "events/envelope.schema.json"
    example = load(ROOT / "examples/events/envelope.example.json")
    example["payload"] = {"skill": "slides", "input": {}}
    with pytest.raises(ValidationError):
        validate_example(load(path), example, path)
