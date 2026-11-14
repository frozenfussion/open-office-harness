# SPDX-License-Identifier: AGPL-3.0-only
import errno
import json
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

MOCK_COMMAND = r"""#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

fixture = Path(os.environ["OOH_ADMIN_FIXTURE"])
state = json.loads(fixture.read_text())
args = sys.argv[1:]
for secret in (state["password"], state["token"], state["bootstrap_password"]):
    assert not any(arg == secret or (len(secret) > 3 and secret in arg) for arg in args)
command = Path(sys.argv[0]).name
if command == "jq":
    os.execv(os.environ["OOH_REAL_JQ"], ["jq", *args])
if command == "kubectl":
    if args[:2] == ["config", "view"]:
        print("apiVersion: v1\nkind: Config\nclusters: []" if "--flatten" in args else "https://127.0.0.1:6443")
    elif "nodes" in args and "get" in args:
        print(json.dumps({"items": [{"spec": {"providerID": "k3s://fixture"}}]}))
    elif "secret" in args and "keycloak-bootstrap" in args and "get" in args:
        print(json.dumps({"data": {key:base64.b64encode(state["bootstrap_"+key].encode()).decode() for key in ("username","password")}}))
    else:
        raise SystemExit("unexpected fixture kubectl call")
    raise SystemExit(0)
url = urlsplit(args[-1])
method = args[args.index("-X")+1] if "-X" in args else "GET"
body = None
status = 200
reply_kind = ""
if url.path == "/realms/master/protocol/openid-connect/token":
    assert args[args.index("--data-binary")+1] == "@-"
    form = parse_qs(sys.stdin.read())
    assert form["password"] == [state["bootstrap_password"]]
    state["token_at"] = state["now"]
    state["events"].append("token")
    body = {"access_token":state["token"],"expires_in":60}
    reply_kind = "token"
else:
    config = args[args.index("--config")+1]
    auth = sys.stdin.read() if config == "-" else Path(config).read_text()
    assert auth.strip() == 'header = "Authorization: Bearer '+state["token"]+'"'
    assert state["now"]-state["token_at"] <= 60
    if url.path == "/admin/realms/ooh/roles/ooh-admin/users":
        reply_kind = "admins"
        limit = int(parse_qs(url.query).get("max",["100"])[0])
        body = state["users"] if limit < 0 else state["users"][:limit]
    elif url.path == "/admin/realms/ooh/users" and method == "GET":
        assert args[args.index("--data-urlencode")+1] == "username@/dev/fd/4"
        assert Path("/dev/fd/4").read_text() == "fixture-human"
        reply_kind = "created-user" if state.get("created") else "lookup"
        body = [state["existing"]] if state.get("existing") else ([{"id":"fixture-user"}] if state.get("created") else [])
    elif url.path == "/admin/realms/ooh/users" and method == "POST":
        assert args[args.index("--data-binary")+1] == "@-"
        payload = json.load(sys.stdin)
        assert payload["credentials"] == [{"type":"password","value":state["password"],"temporary":False}]
        assert payload["attributes"] == {"ooh-first-admin":["true"]}
        assert payload["requiredActions"] == [] and payload["enabled"] is True
        status = state.get("create_status",201)
        if status == 400:
            reason = "Requested username is unavailable"
            if state.get("reflect_secrets"):
                reason += " "+state["password"]+" "+state["token"]
            body = {state.get("error_field","errorMessage"):reason}
        else:
            state["created"] = True
            body = None
    elif url.path == "/admin/realms/ooh/roles/ooh-admin":
        reply_kind = "role"
        body = {"id":"fixture-role","name":"ooh-admin"}
    elif url.path.endswith("/role-mappings/realm") and method == "POST":
        assert json.load(sys.stdin) == [{"id":"fixture-role","name":"ooh-admin"}]
        state["assigned"] = True
        status = 204
    else:
        raise SystemExit("unexpected fixture curl call")
replacement = fixture.with_suffix(".next")
replacement.write_text(json.dumps(state))
replacement.replace(fixture)
if reply_kind == state.get("bad_reply"):
    print(state["bad_body"],end="")
elif body is not None:
    print(json.dumps(body),end="")
print("\n"+str(status),end="")
"""


class FirstAdminFixtureTests(unittest.TestCase):
    def run_fixture(
        self,
        users: list[dict[str, str]],
        *,
        slow: bool = False,
        password: str | None = None,
        **options: object,
    ) -> tuple[str, dict]:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(
            prefix="ooh-first-admin-fixture-"
        ) as directory:
            home = Path(directory)
            commands = home / "bin"
            commands.mkdir()
            for command in ("kubectl", "curl", "jq"):
                mock = commands / command
                mock.write_text(MOCK_COMMAND)
                mock.chmod(0o700)
            fixture = home / "state.json"
            state = dict(
                users=users,
                now=0,
                events=[],
                password=password or "fixture-" + os.urandom(16).hex(),
                token="fixture-token-" + os.urandom(16).hex(),
                bootstrap_username="fixture-bootstrap",
                bootstrap_password=os.urandom(16).hex(),
                **options,
            )
            fixture.write_text(json.dumps(state))
            environment = dict(
                os.environ,
                HOME=str(home),
                PATH=f"{commands}{os.pathsep}{os.environ['PATH']}",
                OOH_TARGET="do",
                OOH_ADMIN_FIXTURE=str(fixture),
                OOH_REAL_JQ=shutil.which("jq") or "/usr/bin/jq",
            )
            for key in ("OOH_FROZEN_TARGET", "OOH_FROZEN_KUBECONFIG"):
                environment.pop(key, None)
            prompts = [
                (b"First admin username: ", "fixture-human"),
                (b"First admin email: ", "fixture-human@example.invalid"),
                (b"First admin password (hidden): ", state["password"]),
                (b"Repeat password (hidden): ", state["password"]),
            ]
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
            answered = 0
            deadline = time.monotonic() + 20
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
                    if answered < len(prompts) and prompts[answered][0] in output:
                        current = json.loads(fixture.read_text())
                        self.assertNotIn(
                            "token_at", current, "token requested before all input"
                        )
                        if slow:
                            time.sleep(0.1)
                            current["now"] = answered * 25
                        current["events"].append(f"input-{answered}")
                        fixture.write_text(json.dumps(current))
                        os.write(master, (prompts[answered][1] + "\n").encode())
                        answered += 1
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)
            text = output.decode()
            result = json.loads(fixture.read_text())
            self.assertEqual(answered, 4, text)
            private_output = "\n".join(
                line
                for line in text.splitlines()
                if not line.startswith(("First admin username:", "First admin email:"))
            )
            for secret in (
                state["password"],
                state["token"],
                state["bootstrap_password"],
            ):
                if len(secret) > 3:
                    self.assertNotIn(secret, private_output)
                else:
                    self.assertNotIn(secret, private_output.splitlines())
            result["exit_code"] = process.returncode
            return text, result

    def assert_created(self, users: list[dict[str, str]]) -> None:
        text, state = self.run_fixture(users)
        self.assertEqual(state["exit_code"], 0, text)
        self.assertTrue(state["created"] and state["assigned"])
        self.assertIn("First admin created", text)

    def assert_existing(self, users: list[dict[str, str]]) -> None:
        text, state = self.run_fixture(users)
        self.assertEqual(state["exit_code"], 0, text)
        self.assertIn("First admin already exists; no changes made", text)
        self.assertNotIn("created", state)
        self.assertNotIn("assigned", state)

    def test_only_stage_check_service_account_asks_for_details(self) -> None:
        self.assert_created(
            [
                {
                    "username": "service-account-ooh-stage-check",
                    "serviceAccountClientId": "ooh-stage-check",
                }
            ]
        )

    def test_service_account_username_without_client_id_asks_for_details(self) -> None:
        self.assert_created([{"username": "service-account-ooh-stage-check"}])

    def test_service_account_client_id_without_prefix_asks_for_details(self) -> None:
        self.assert_created(
            [
                {
                    "username": "fixture-service",
                    "serviceAccountClientId": "ooh-stage-check",
                }
            ]
        )

    def test_human_administrator_skips_creation(self) -> None:
        self.assert_existing([{"username": "fixture-human-admin"}])

    def test_service_account_before_human_still_skips_creation(self) -> None:
        self.assert_existing(
            [
                {"username": "service-account-ooh-stage-check"},
                {"username": "fixture-human-admin"},
            ]
        )

    def test_human_after_many_service_accounts_still_skips_creation(self) -> None:
        self.assert_existing(
            [{"username": f"service-account-fixture-{n}"} for n in range(101)]
            + [{"username": "fixture-human-admin"}]
        )

    def test_slow_input_precedes_token_and_does_not_expire_it(self) -> None:
        text, state = self.run_fixture([], slow=True)
        self.assertEqual(state["exit_code"], 0, text)
        self.assertEqual(state["token_at"], 75)
        self.assertEqual(
            state["events"], ["input-0", "input-1", "input-2", "input-3", "token"]
        )

    def test_keycloak_error_message_is_reported(self) -> None:
        text, state = self.run_fixture([], create_status=400)
        self.assertEqual(state["exit_code"], 1)
        self.assertIn(
            "STOP: Keycloak refused request (HTTP 400): Requested username is unavailable",
            text,
        )
        self.assertNotIn("admin request failed", text)

    def test_keycloak_error_description_is_reported_and_secrets_redacted(self) -> None:
        text, state = self.run_fixture(
            [], create_status=400, error_field="error_description", reflect_secrets=True
        )
        self.assertEqual(state["exit_code"], 1)
        self.assertIn("Requested username is unavailable", text)
        self.assertIn("[REDACTED]", text)

    def test_short_password_does_not_garble_keycloak_reason(self) -> None:
        text, state = self.run_fixture([], password="a", create_status=400)
        self.assertEqual(state["exit_code"], 1)
        self.assertIn(
            "STOP: Keycloak refused request (HTTP 400): Requested username is unavailable",
            text,
        )
        self.assertNotIn("[REDACTED]", text)

    def test_redaction_only_matches_whole_literal_values(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (root / "install/50-first-admin.sh").read_text()
        functions = source[
            source.index("is_value_boundary() {") : source.index("request() {")
        ]
        cases = [
            (
                "a",
                "Requested username is unavailable",
                "Requested username is unavailable",
            ),
            ("a", "aa a aa", "aa [REDACTED] aa"),
            ("a", "a", "[REDACTED]"),
            ("a", " a ", " [REDACTED] "),
            ("a", "'a'", "'[REDACTED]'"),
            ("a", '"a"', '"[REDACTED]"'),
            ("a", "password:a", "password:[REDACTED]"),
            ("a", "a=token", "[REDACTED]=token"),
            ("a", "a, cat", "a, cat"),
            ("a.*[x]", "value='a.*[x]'", "value='[REDACTED]'"),
        ]
        for secret, reason, expected in cases:
            with self.subTest(secret=secret, reason=reason):
                result = subprocess.run(
                    [
                        "bash",
                        "-euc",
                        functions
                        + '\nreason=$TEST_REASON\nredact_value "$TEST_SECRET"\nprintf %s "$reason"',
                    ],
                    env=dict(os.environ, TEST_REASON=reason, TEST_SECRET=secret),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(result.stdout, expected)

    def test_invalid_success_replies_have_clear_stop_lines(self) -> None:
        cases = [
            ("token", "{}", "Keycloak token reply had no access token"),
            ("token", "", "Keycloak token reply had no access token"),
            ("role", "not json", "ooh-admin role could not be read"),
            ("role", "{}", "ooh-admin role could not be read"),
            ("admins", "not json", "Keycloak administrator list could not be read"),
            ("lookup", "not json", "Keycloak user lookup could not be read"),
            ("created-user", "not json", "Keycloak first-admin user could not be read"),
        ]
        for reply, body, message in cases:
            with self.subTest(reply=reply, body=body):
                text, state = self.run_fixture([], bad_reply=reply, bad_body=body)
                self.assertEqual(state["exit_code"], 1)
                self.assertIn("STOP: " + message, text)
                self.assertNotIn("First admin already exists", text)
                self.assertFalse(text.rstrip().endswith("DONE"))

    def test_one_character_password_is_accepted(self) -> None:
        text, state = self.run_fixture([], password="z")
        self.assertEqual(state["exit_code"], 0, text)
        self.assertTrue(state["created"])

    def test_password_may_match_username_or_email(self) -> None:
        for password in ("fixture-human", "fixture-human@example.invalid"):
            with self.subTest(password=password):
                text, state = self.run_fixture([], password=password)
                self.assertEqual(state["exit_code"], 0, text)
                self.assertTrue(state["created"])

    def test_unmarked_existing_user_is_never_overwritten(self) -> None:
        text, state = self.run_fixture(
            [], existing={"id": "fixture-user", "attributes": {}}
        )
        self.assertEqual(state["exit_code"], 1)
        self.assertIn("username already exists", text)
        self.assertNotIn("created", state)
        self.assertNotIn("assigned", state)

    def test_marked_existing_user_only_completes_role(self) -> None:
        text, state = self.run_fixture(
            [],
            existing={
                "id": "fixture-user",
                "attributes": {"ooh-first-admin": ["true"]},
            },
        )
        self.assertEqual(state["exit_code"], 0, text)
        self.assertNotIn("created", state)
        self.assertTrue(state["assigned"])
        self.assertIn("password unchanged", text)


class RealmPasswordPolicyTests(unittest.TestCase):
    def test_fresh_realm_has_no_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        line = next(
            line.strip()
            for line in (root / "deploy/platform/keycloak/realm-ooh.yaml")
            .read_text()
            .splitlines()
            if line.strip().startswith("passwordPolicy:")
        )
        self.assertEqual(line, 'passwordPolicy: ""')

    def test_sync_clears_policy_and_verifies_empty_or_omitted(self) -> None:
        for policy in ("", None, "legacy-policy"):
            with self.subTest(policy=policy):
                root = Path(__file__).resolve().parents[2]
                source = (root / "install/35-realm-sync.sh").read_text()
                block = source[
                    source.index("# Keep other realm settings") : source.index(
                        "profile_attributes="
                    )
                ]
                settings = {
                    "displayName": "Open Office Harness",
                    "loginTheme": "ooh",
                    "registrationAllowed": True,
                    "registrationEmailAsUsername": True,
                    "loginWithEmailAllowed": True,
                    "duplicateEmailsAllowed": False,
                    "editUsernameAllowed": False,
                    "verifyEmail": False,
                    "resetPasswordAllowed": False,
                    "internationalizationEnabled": True,
                    "supportedLocales": ["en"],
                    "defaultLocale": "en",
                }
                if policy is not None:
                    settings["passwordPolicy"] = policy
                script = (
                    """set -euo pipefail
stop() { echo "STOP: $*" >&2; exit 1; }
registration_allowed=true
seen=false
kcadm() {
  if [[ "$1" == update ]]; then
    for value in "$@"; do [[ "$value" != 'passwordPolicy=""' ]] || seen=true; done
    [[ "$seen" == true ]]
  else
    [[ "$seen" == true ]]
    printf '%s' "$MOCK_SETTINGS"
  fi
}
"""
                    + block
                )
                result = subprocess.run(
                    ["bash", "-c", script],
                    env=dict(os.environ, MOCK_SETTINGS=json.dumps(settings)),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode == 0, policy != "legacy-policy", result.stderr
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
