# SPDX-License-Identifier: AGPL-3.0-only
"""Offline review regressions; AWS, Terraform and Kubernetes calls are stubbed."""

import contextlib
import io
import json
import os
import re
import shlex
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft201909Validator

ROOT = Path(__file__).resolve().parents[5]
CLUSTER = ROOT / "install/82-aws-cluster.sh"
DESTROY = ROOT / "install/85-aws-destroy.sh"
CHECK = ROOT / "install/86-check-aws.sh"


class ReviewFixtures(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ooh-review-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)

    def shell(
        self, body: str, source: Path = CLUSTER, data: dict | None = None
    ) -> subprocess.CompletedProcess[str]:
        fixture = self.home / "fixture.json"
        fixture.write_text(json.dumps(data or {}))
        # Stub every external account/cluster tool, including unexpected calls.
        script = (
            f"source {shlex.quote(str(source))}\n"
            + """
aws() { printf 'UNEXPECTED AWS CALL\n' >&2; return 97; }
kubectl() { printf 'UNEXPECTED KUBERNETES CALL\n' >&2; return 97; }
terraform() { printf 'UNEXPECTED TERRAFORM CALL\n' >&2; return 97; }
"""
            + body
        )
        result = subprocess.run(
            ["bash", "-c", script],
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(self.home), "FIXTURE": str(fixture)},
            timeout=10,
        )
        self.assertNotIn("UNEXPECTED", result.stdout + result.stderr)
        return result

    def guard(
        self, number: int, changes: list[tuple[str, list[str]]]
    ) -> subprocess.CompletedProcess[str]:
        return self.shell(
            f'terraform() {{ cat "$FIXTURE"; }}; paid_guard {number} cluster unused',
            data={
                "resource_changes": [
                    {"type": kind, "change": {"actions": actions}}
                    for kind, actions in changes
                ]
            },
        )

    def test_plan_two_expected_creates_and_empty_rerun(self) -> None:
        changes = [
            (kind, ["create"])
            for kind in ("aws_nat_gateway", "aws_eip", "aws_eks_node_group")
        ]
        self.assertEqual(self.guard(2, changes).returncode, 0)
        self.assertEqual(self.guard(2, []).returncode, 0)
        self.assertEqual(
            self.guard(2, [("aws_eks_node_group", ["no-op"])]).returncode, 0
        )

    def test_failed_addon_replacement_is_not_a_paid_change(self) -> None:
        for actions in (["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions):
                changes = [("aws_eks_addon", actions)] + [
                    (kind, ["no-op"])
                    for kind in ("aws_nat_gateway", "aws_eip", "aws_eks_node_group")
                ]
                self.assertEqual(self.guard(2, changes).returncode, 0)
                result = self.guard(
                    2, changes + [("aws_eks_node_group", ["delete", "create"])]
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("STOP: paid resource deletion/replacement", result.stderr)

    def test_unexpected_paid_counts_stop(self) -> None:
        for changes in (
            [("aws_nat_gateway", ["create"])],
            [("aws_instance", ["create"])],
            [("aws_eks_cluster", ["create"])] * 2,
        ):
            with self.subTest(changes=changes):
                result = self.guard(2, changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("STOP: paid resource counts differ", result.stderr)

    def test_any_paid_delete_stops_in_every_plan(self) -> None:
        for number in (1, 2, 3):
            for kind in (
                "aws_nat_gateway",
                "aws_eip",
                "aws_instance",
                "aws_eks_node_group",
                "aws_lb",
                "aws_ebs_volume",
                "aws_eks_cluster",
            ):
                for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
                    with self.subTest(number=number, kind=kind, actions=actions):
                        result = self.guard(number, [(kind, actions)])
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            "STOP: paid resource deletion/replacement", result.stderr
                        )

    def test_plan_one_allows_only_one_cluster_create_or_empty(self) -> None:
        self.assertEqual(self.guard(1, []).returncode, 0)
        self.assertEqual(self.guard(1, [("aws_eks_cluster", ["create"])]).returncode, 0)
        for changes in (
            [("aws_eks_cluster", ["create"])] * 2,
            [("aws_lb", ["create"])],
            [("aws_ebs_volume", ["create"])],
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.guard(1, changes).returncode, 0)

    def test_plan_one_replacement_stops_before_confirmation_or_apply(self) -> None:
        result = self.shell(
            """
aws_setup() { :; }; check_signin() { :; }; check_age() { :; }
price_table() { :; }; init_root() { :; }; show_plan() { :; }
terraform() { if [[ $2 == show ]]; then cat "$FIXTURE"; fi; }
confirm() { printf 'PROMPT REACHED\n'; }
apply_plan() { printf 'APPLY REACHED\n'; }
cluster_main
""",
            data={
                "resource_changes": [
                    {
                        "address": "aws_eks_cluster.main",
                        "type": "aws_eks_cluster",
                        "change": {"actions": ["delete", "create"]},
                    }
                ]
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("paid resource deletion/replacement", result.stderr)
        self.assertNotIn("PROMPT REACHED", result.stdout)
        self.assertNotIn("APPLY REACHED", result.stdout)

    def test_missing_template_tag_records_id_and_continues(self) -> None:
        result = self.shell(
            """
AWS_ACCOUNT=fixture-account
aws() {
    case "$1 $2" in
        'eks describe-nodegroup') printf 'fixture-group';;
        'autoscaling describe-auto-scaling-groups') cat "$FIXTURE";;
        'ec2 describe-launch-templates') printf '[]';;
        *) return 97;;
    esac
}
save_setting() { printf '%s=%s\n' "$1" "$2" > "$HOME/saved"; }
capture_node_tags
printf 'PLAN 3 CONTINUES\n'
""",
            data={
                "AutoScalingGroups": [
                    {
                        "Tags": [],
                        "MixedInstancesPolicy": {
                            "LaunchTemplate": {
                                "LaunchTemplateSpecification": {
                                    "LaunchTemplateId": "lt-fixture"
                                }
                            }
                        },
                    }
                ]
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FAIL: launch template has no eks:cluster-name", result.stdout)
        self.assertIn("PLAN 3 CONTINUES", result.stdout)
        self.assertEqual((self.home / "saved").read_text(), "EKS_LT_ID=lt-fixture\n")

    @staticmethod
    def schema() -> dict:
        fixture = (
            Path(__file__).with_name("fixtures")
            / "ebs-addon-schema-v1.68.0-eksbuild.1.json"
        )
        return json.loads(fixture.read_text())

    def test_schema_guard_accepts_saved_aws_schema(self) -> None:
        schema = self.schema()
        properties = schema["properties"]["controller"]["properties"]
        self.assertNotIn("region", properties)
        self.assertNotIn("k8sTagClusterId", properties)
        result = self.shell('aws() { cat "$FIXTURE"; }; check_ebs_schema', data=schema)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_guard_does_not_require_controller_env(self) -> None:
        schema = self.schema()
        del schema["properties"]["controller"]["properties"]["env"]
        result = self.shell('aws() { cat "$FIXTURE"; }; check_ebs_schema', data=schema)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_guard_follows_references(self) -> None:
        schema = self.schema()
        schema["$defs"]["Controller"] = schema["properties"]["controller"]
        schema["properties"]["controller"] = {"$ref": "#/$defs/Controller"}
        result = self.shell('aws() { cat "$FIXTURE"; }; check_ebs_schema', data=schema)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ebs_terraform_configuration_matches_saved_aws_schema(self) -> None:
        source = (ROOT / "infra/terraform/aws/cluster/addons.tf").read_text()
        start = source.index("jsonencode(") + len("jsonencode(")
        configuration = (
            source[start : source.index("\n  depends_on", start)]
            .strip()
            .removesuffix(")")
        )
        # Evaluate only locals in an empty directory: no provider, backend or account call.
        local_tags = (ROOT / "infra/terraform/aws/cluster/main.tf").read_text()
        (self.home / "main.tf").write_text(
            local_tags + "\nlocals {\nconfiguration = " + configuration + "\n}\n"
        )
        result = subprocess.run(
            ["terraform", f"-chdir={self.home}", "console"],
            input="jsonencode(local.configuration)\n",
            text=True,
            capture_output=True,
            check=True,
        )
        configuration = json.loads(json.loads(result.stdout))
        schema = self.schema()
        Draft201909Validator.check_schema(schema)
        validator = Draft201909Validator(schema)
        validator.validate(configuration)
        controller = configuration["controller"]
        self.assertNotIn("env", controller)
        self.assertEqual(controller["additionalArgs"], ["--k8s-tag-cluster-id=ooh-aws"])
        self.assertEqual(
            controller["extraVolumeTags"],
            {
                "project": "open-office-harness",
                "stage": "4b",
                "managed-by": "terraform",
                "ooh-stage": "4b",
            },
        )
        for legacy in ({"region": "ap-southeast-1"}, {"k8sTagClusterId": "ooh-aws"}):
            self.assertFalse(validator.is_valid({"controller": legacy}))

    def test_schema_does_not_inspect_tag_map(self) -> None:
        for tags_schema in (
            {"type": "object"},
            {"type": "object", "additionalProperties": False},
        ):
            with self.subTest(tags_schema=tags_schema):
                schema = self.schema()
                schema["properties"]["controller"]["properties"]["extraVolumeTags"] = (
                    tags_schema
                )
                result = self.shell(
                    'aws() { cat "$FIXTURE"; }; check_ebs_schema', data=schema
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_schema_missing_each_named_property_stops(self) -> None:
        for name in ("additionalArgs", "extraVolumeTags"):
            with self.subTest(name=name):
                schema = self.schema()
                del schema["properties"]["controller"]["properties"][name]
                result = self.shell(
                    'aws() { cat "$FIXTURE"; }; check_ebs_schema', data=schema
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"STOP: EBS CSI add-on configuration key controller.{name} not in AWS's schema",
                    result.stderr,
                )

    def test_inventory_includes_tagset_network_interfaces(self) -> None:
        program = re.search(r"<<'PY'\n(.*?)\nPY", DESTROY.read_text(), re.DOTALL).group(
            1
        )
        keys = {
            "describe-instances": "Reservations",
            "describe-volumes": "Volumes",
            "describe-nat-gateways": "NatGateways",
            "describe-addresses": "Addresses",
            "describe-network-interfaces": "NetworkInterfaces",
            "describe-security-groups": "SecurityGroups",
            "describe-launch-templates": "LaunchTemplates",
            "describe-vpcs": "Vpcs",
            "describe-subnets": "Subnets",
            "describe-route-tables": "RouteTables",
            "describe-internet-gateways": "InternetGateways",
            "describe-load-balancers": "LoadBalancers",
            "describe-target-groups": "TargetGroups",
            "describe-auto-scaling-groups": "AutoScalingGroups",
            "list-clusters": "clusters",
            "describe-log-groups": "logGroups",
            "list-keys": "Keys",
            "list-roles": "Roles",
            "list-policies": "Policies",
            "list-instance-profiles": "InstanceProfiles",
        }

        def fake_run(command: list[str], **kwargs: object) -> types.SimpleNamespace:
            operation = command[4]
            if operation == "describe-regions":
                data = {"Regions": [{"RegionName": "ap-southeast-1"}]}
            elif operation == "describe-network-interfaces":
                data = {
                    "NetworkInterfaces": [
                        {
                            "NetworkInterfaceId": "eni-node",
                            "TagSet": [{"Key": "stage", "Value": "4b"}],
                        },
                        {
                            "NetworkInterfaceId": "eni-leak",
                            "TagSet": [
                                {
                                    "Key": "cluster.k8s.amazonaws.com/name",
                                    "Value": "ooh-aws",
                                }
                            ],
                        },
                        {"NetworkInterfaceId": "eni-unrelated", "TagSet": []},
                    ]
                }
            else:
                data = {keys[operation]: []}
            return types.SimpleNamespace(
                returncode=0, stdout=json.dumps(data), stderr=""
            )

        output = io.StringIO()
        with (
            patch("subprocess.run", side_effect=fake_run),
            contextlib.redirect_stdout(output),
        ):
            # Execute the trusted repository program with all AWS subprocess calls stubbed.
            exec(compile(program, str(DESTROY), "exec"), {})  # noqa: S102
        rows = json.loads(output.getvalue())
        self.assertEqual({row["id"] for row in rows}, {"eni-node", "eni-leak"})
        self.assertEqual(
            next(row for row in rows if row["id"] == "eni-node")["tags"],
            {"stage": "4b"},
        )

    def test_destroy_logs_out_on_refusal_and_early_failure(self) -> None:
        for body in (
            'check_signin() { stop "expired fixture"; }; destroy_main',
            'check_signin() { :; }; check_age() { stop "old fixture"; }; destroy_main --all',
            'check_signin() { :; }; check_age() { confirm "Type yes" <<< no; }; destroy_main',
        ):
            with self.subTest(body=body):
                result = self.shell(
                    """
aws_setup() { :; }
aws() { [[ $1 == logout ]] && printf 'LOGGED OUT\n'; }
"""
                    + body,
                    source=DESTROY,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LOGGED OUT", result.stdout)
                self.assertNotIn("DONE", result.stdout)

    def test_sweep_only_does_not_log_out(self) -> None:
        result = self.shell(
            """
aws_setup() { :; }; check_signin() { :; }; sweep_empty() { :; }
destroy_main --sweep-only
""",
            source=DESTROY,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "DONE\n")

    def test_destroy_exit_reports_done_only_after_logout_succeeds(self) -> None:
        for status in (0, 1):
            with self.subTest(status=status):
                result = self.shell(
                    f"""
AWS_PLANS=()
aws() {{ printf 'LOGOUT ATTEMPTED\n'; return {status}; }}
trap destroy_exit EXIT
""",
                    source=DESTROY,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn("LOGOUT ATTEMPTED", result.stdout)
                if status == 0:
                    self.assertEqual(result.stdout, "LOGOUT ATTEMPTED\nDONE\n")
                else:
                    self.assertNotIn("DONE", result.stdout)
                    self.assertIn("STOP: AWS logout failed", result.stderr)

    def test_destroy_waits_for_target_and_security_groups(self) -> None:
        for kind in ("target", "security"):
            with self.subTest(kind=kind):
                result = self.shell(
                    """
printf '0' > "$HOME/round"
aws() {
    [[ $1 == --region && $2 == ap-southeast-1 ]] || return 97
    case "$3 $4" in
        'elbv2 describe-target-groups') printf '{"TargetGroups":[{"TargetGroupArn":"target-fixture"}]}' ;;
        'elbv2 describe-tags')
            if [[ $(cat "$HOME/round") == 0 && $(jq -r '.kind' "$FIXTURE") == target ]]; then
                printf '{"TagDescriptions":[{"Tags":[{"Key":"elbv2.k8s.aws/cluster","Value":"ooh-aws"}]}]}'
            else printf '{"TagDescriptions":[{"Tags":[]}]}' ; fi ;;
        'ec2 describe-security-groups')
            if [[ $(cat "$HOME/round") == 0 && $(jq -r '.kind' "$FIXTURE") == security ]]; then
                printf '{"SecurityGroups":[{"GroupId":"sg-fixture"}]}'
            else printf '{"SecurityGroups":[]}' ; fi ;;
        *) return 97;;
    esac
}
sleep() { printf 'WAITED\n'; printf '1' > "$HOME/round"; }
wait_no_controller_resources
printf 'CLEAN\n'
""",
                    source=DESTROY,
                    data={"kind": kind},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "WAITED\nCLEAN\n")

    def test_running_inventory_allows_backend_security_group_only_in_cluster_vpc(
        self,
    ) -> None:
        program = re.search(r"<<'PY'\n(.*?)\nPY", CHECK.read_text(), re.DOTALL).group(1)
        fixtures = {
            "cluster": {"values": {}},
            "addons": {"values": {}},
            "nodes": {"items": []},
            "pv": {"items": []},
            "lb": {
                "LoadBalancerArn": "fixture:loadbalancer/net/front",
                "SecurityGroups": ["sg-front"],
            },
            "asg": {
                "AutoScalingGroups": [
                    {"AutoScalingGroupName": "fixture-group", "Instances": []}
                ]
            },
            "eks": {
                "cluster": {
                    "resourcesVpcConfig": {
                        "vpcId": "vpc-fixture",
                        "clusterSecurityGroupId": "sg-eks",
                    }
                }
            },
        }
        for name, data in fixtures.items():
            (self.home / f"{name}.json").write_text(json.dumps(data))
        for vpc, cluster, resource, expected in (
            ("vpc-fixture", "ooh-aws", "backend-sg", 0),
            ("vpc-other", "ooh-aws", "backend-sg", 1),
            ("vpc-fixture", "other-cluster", "backend-sg", 1),
            ("vpc-fixture", "ooh-aws", "unrelated-sg", 1),
        ):
            with self.subTest(vpc=vpc, cluster=cluster, resource=resource):
                row = {
                    "region": "ap-southeast-1",
                    "type": "sg",
                    "id": "sg-backend",
                    "arn": "sg-backend",
                    "raw": {"VpcId": vpc},
                    "tags": {
                        "elbv2.k8s.aws/cluster": cluster,
                        "elbv2.k8s.aws/resource": resource,
                    },
                }
                (self.home / "inventory.json").write_text(json.dumps([row]))
                output = io.StringIO()
                with (
                    patch("sys.argv", ["fixture", str(self.home), "lt-fixture"]),
                    contextlib.redirect_stdout(output),
                    self.assertRaises(SystemExit) as stopped,
                ):
                    # Execute only the trusted membership program on local fixture files.
                    exec(compile(program, str(CHECK), "exec"), {})  # noqa: S102
                self.assertEqual(stopped.exception.code, expected)
                if expected:
                    self.assertIn(
                        "FAIL: unexpected ap-southeast-1 sg sg-backend",
                        output.getvalue(),
                    )
                else:
                    self.assertEqual(output.getvalue(), "")

    def test_destroy_retries_failed_target_group_tag_read(self) -> None:
        result = self.shell(
            """
printf '0' > "$HOME/round"
aws() {
    [[ $1 == --region && $2 == ap-southeast-1 ]] || return 97
    case "$3 $4" in
        'elbv2 describe-target-groups')
            if [[ $(cat "$HOME/round") == 0 ]]; then
                printf '{"TargetGroups":[{"TargetGroupArn":"target-disappearing"}]}'
            else printf '{"TargetGroups":[]}' ; fi ;;
        'elbv2 describe-tags') printf 'TargetGroupNotFound fixture\n' >&2; return 1 ;;
        'ec2 describe-security-groups') printf '{"SecurityGroups":[]}' ;;
        *) return 97;;
    esac
}
sleep() { printf 'RETRIED\n'; printf '1' > "$HOME/round"; }
wait_no_controller_resources
printf 'CLEAN\n'
""",
            source=DESTROY,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TargetGroupNotFound fixture", result.stderr)
        self.assertEqual(result.stdout, "RETRIED\nCLEAN\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
