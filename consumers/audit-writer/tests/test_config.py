# SPDX-License-Identifier: AGPL-3.0-only
import os
import re
from pathlib import Path

import pytest

from consumer.config import Config


def test_environment_uses_exact_deployed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[3]
    manifests = root / "deploy/apps/audit-writer"
    configmap = (manifests / "configmap.yaml").read_text()
    deployment = (
        (manifests / "deployment.yaml").read_text().split("      containers:", 1)[1]
    )
    keys = set(re.findall(r"^  (AW_[A-Z_]+):", configmap, re.MULTILINE))
    keys.update(re.findall(r"^        - name: (AW_[A-Z_]+)$", deployment, re.MULTILINE))
    values = {
        "AW_OIDC_ISSUER": "https://identity.invalid/realms/ooh",
        "AW_KAFKA_BOOTSTRAP": "kafka.invalid:9092",
        "AW_KAFKA_USERNAME": "audit-writer",
        "AW_KAFKA_PASSWORD": "synthetic-password",
        "AW_DB_CONNECTION": "synthetic-test-connection",
    }
    assert keys == set(values)
    for key in list(os.environ):
        if key.startswith("AW_"):
            monkeypatch.delenv(key)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Config.environment()
    assert settings.username == "audit-writer"
    assert settings.bootstrap == "kafka.invalid:9092"
    assert settings.password == "synthetic-password"
