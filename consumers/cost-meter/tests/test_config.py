# SPDX-License-Identifier: AGPL-3.0-only
import os
import re
from pathlib import Path

import pytest

from consumer.config import Config


def test_environment_uses_exact_deployed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[3]
    manifests = root / "deploy/apps/cost-meter"
    configmap = (manifests / "configmap.yaml").read_text()
    deployment = (
        (manifests / "deployment.yaml").read_text().split("      containers:", 1)[1]
    )
    keys = set(re.findall(r"^  (CM_[A-Z_]+):", configmap, re.MULTILINE))
    keys.update(re.findall(r"^        - name: (CM_[A-Z_]+)$", deployment, re.MULTILINE))
    values = {
        "CM_OIDC_ISSUER": "https://identity.invalid/realms/ooh",
        "CM_KAFKA_BOOTSTRAP": "kafka.invalid:9092",
        "CM_KAFKA_USERNAME": "cost-meter",
        "CM_KAFKA_PASSWORD": "synthetic-password",
        "CM_DB_CONNECTION": "synthetic-test-connection",
    }
    assert keys == set(values)
    for key in list(os.environ):
        if key.startswith("CM_"):
            monkeypatch.delenv(key)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Config.environment()
    assert settings.username == "cost-meter"
    assert settings.bootstrap == "kafka.invalid:9092"
    assert settings.password == "synthetic-password"
