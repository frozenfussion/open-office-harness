# SPDX-License-Identifier: AGPL-3.0-only
import errno
import json
import os
import pty
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

MOCK_COMMAND = """#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

args = sys.argv[1:]
if Path(sys.argv[0]).name == "kubectl":
    if args[:2] == ["config", "view"]:
        if "--flatten" in args:
            print("apiVersion: v1\\nkind: Config\\nclusters: []")
        else:
            print("https://127.0.0.1:6443", end="")
    elif "nodes" in args and "get" in args:
        print(json.dumps({"items": [{"spec": {"providerID": "k3s://fixture"}}]}))
    elif "secret" in args and "keycloak-bootstrap" in args and "get" in args:
        print(json.dumps({"data": {
            key: base64.b64encode(os.urandom(16).hex().encode()).decode()
            for key in ("username", "password")
        }}))
    else:
        raise SystemExit("unexpected fixture kubectl call")
else:
    url = urlsplit(args[-1])
    if url.path == "/realms/master/protocol/openid-connect/token":
        assert args[args.index("--data-binary") + 1] == "@-"
        assert sys.stdin.read().startswith("client_id=admin-cli&grant_type=password&")
        print(json.dumps({"access_token": os.urandom(16).hex()}))
    elif url.path == "/admin/realms/ooh/roles/ooh-admin/users":
        assert args[args.index("--config") + 1] == "-"
        assert sys.stdin.read().startswith('header = "Authorization: Bearer ')
        users = json.loads(Path(os.environ["OOH_ADMIN_FIXTURE"]).read_text())
        limit = int(parse_qs(url.query).get("max", ["100"])[0])
        print(json.dumps(users if limit < 0 else users[:limit]))
    else:
        raise SystemExit("unexpected fixture curl call; writes are forbidden")
"""


class FirstAdminFixtureTests(unittest.TestCase):
    def run_fixture(self, users: list[dict[str, str]], asks: bool) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(
            prefix="ooh-first-admin-fixture-"
        ) as directory:
            home = Path(directory)
            commands = home / "bin"
            commands.mkdir()
            for command in ("kubectl", "curl"):
                mock = commands / command
                mock.write_text(MOCK_COMMAND)
                mock.chmod(0o700)
            fixture = home / "users.json"
            fixture.write_text(json.dumps(users))
            environment = dict(
                os.environ,
                HOME=str(home),
                PATH=f"{commands}{os.pathsep}{os.environ['PATH']}",
                OOH_TARGET="do",
                OOH_ADMIN_FIXTURE=str(fixture),
            )
            for key in ("OOH_FROZEN_TARGET", "OOH_FROZEN_KUBECONFIG"):
                environment.pop(key, None)
            master, slave = pty.openpty()
            process = subprocess.Popen(
                ["bash", str(root / "install/50-first-admin.sh")],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=environment,
            )
            os.close(slave)
            output = bytearray()
            saw_prompt = False
            deadline = time.monotonic() + 15
            try:
                while time.monotonic() < deadline:
                    if not select.select([master], [], [], 0.2)[0]:
                        continue
                    try:
                        chunk = os.read(master, 4096)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    output.extend(chunk)
                    if b"First admin username: " in output and not saw_prompt:
                        saw_prompt = True
                        # End input at the first prompt: no user is ever created by this test.
                        os.write(master, b"\x04")
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)
            text = output.decode()
            self.assertEqual(saw_prompt, asks, text)
            if asks:
                self.assertNotEqual(process.returncode, 0, text)
                self.assertNotIn("First admin already exists", text)
            else:
                self.assertEqual(process.returncode, 0, text)
                self.assertIn("First admin already exists; no changes made", text)
                self.assertTrue(text.rstrip().endswith("DONE"), text)

    def test_only_stage_check_service_account_asks_for_details(self) -> None:
        self.run_fixture(
            [
                {
                    "username": "service-account-ooh-stage-check",
                    "serviceAccountClientId": "ooh-stage-check",
                }
            ],
            asks=True,
        )

    def test_service_account_username_without_client_id_asks_for_details(self) -> None:
        self.run_fixture([{"username": "service-account-ooh-stage-check"}], asks=True)

    def test_service_account_client_id_without_prefix_asks_for_details(self) -> None:
        self.run_fixture(
            [
                {
                    "username": "fixture-service",
                    "serviceAccountClientId": "ooh-stage-check",
                }
            ],
            asks=True,
        )

    def test_human_administrator_skips_creation(self) -> None:
        self.run_fixture([{"username": "fixture-human-admin"}], asks=False)

    def test_service_account_before_human_still_skips_creation(self) -> None:
        self.run_fixture(
            [
                {"username": "service-account-ooh-stage-check"},
                {"username": "fixture-human-admin"},
            ],
            asks=False,
        )

    def test_human_after_many_service_accounts_still_skips_creation(self) -> None:
        self.run_fixture(
            [{"username": f"service-account-fixture-{number}"} for number in range(101)]
            + [{"username": "fixture-human-admin"}],
            asks=False,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
