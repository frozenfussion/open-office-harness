# SPDX-License-Identifier: AGPL-3.0-only
import json
import os
import re
from pathlib import Path

import pytest

from consumer.config import Config


def test_environment_uses_exact_deployed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[3]
    manifests = root / "deploy/apps/safety-watcher"
    configmap = (manifests / "configmap.yaml").read_text()
    deployment = (
        (manifests / "deployment.yaml").read_text().split("      containers:", 1)[1]
    )
    keys = set(re.findall(r"^  (SF_[A-Z_]+):", configmap, re.MULTILINE))
    keys.update(re.findall(r"^        - name: (SF_[A-Z_]+)$", deployment, re.MULTILINE))
    values = {
        "SF_OIDC_ISSUER": "https://identity.invalid/realms/ooh",
        "SF_KAFKA_BOOTSTRAP": "kafka.invalid:9092",
        "SF_KAFKA_USERNAME": "safety-watcher",
        "SF_KAFKA_PASSWORD": "synthetic-password",
        "SF_GATEWAY_URL": "https://gateway.invalid",
        "SF_CLIENT_SECRET": "synthetic-client",
        "SF_THRESHOLD": "0.8",
        "SF_QUESTIONS": json.dumps({"risk": "Is there a risk?"}),
    }
    assert keys == set(values)
    for key in list(os.environ):
        if key.startswith("SF_"):
            monkeypatch.delenv(key)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Config.environment()
    assert settings.username == "safety-watcher"
    assert settings.bootstrap == "kafka.invalid:9092"
    assert settings.password == "synthetic-password"
