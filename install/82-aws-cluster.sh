#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
# shellcheck source=install/81-aws-bootstrap.sh
source "$(dirname "${BASH_SOURCE[0]}")/81-aws-bootstrap.sh"
# Offline fixtures use the saved AWS schema; the run phase rechecks AWS's schema.
check_ebs_schema() {
    aws eks describe-addon-configuration --addon-name aws-ebs-csi-driver --addon-version v1.68.0-eksbuild.1 --query configurationSchema --output text | python3 -c "$(cat <<'PY'
import json,sys
schema=json.load(sys.stdin)
def resolve(s):
    while '$ref' in s:
        node=schema
        for part in s['$ref'].removeprefix('#/').split('/'):
            node=node[part.replace('~1','/').replace('~0','~')]
        s=node
    return s
for path in ('controller.additionalArgs', 'controller.extraVolumeTags'):
    node=schema
    for key in path.split('.'):
        properties=resolve(node).get('properties', {})
        if key not in properties:
            sys.exit(f"STOP: EBS CSI add-on configuration key {path} not in AWS's schema")
        node=properties[key]
PY
)"
}
paid_guard() {
    local number=$1
    terraform -chdir="$TF_ROOT/${2}" show -json "$3" | python3 -c "$(cat <<'PY'
import collections,json,sys
paid={'aws_nat_gateway','aws_eip','aws_instance','aws_eks_node_group','aws_lb','aws_ebs_volume','aws_eks_cluster'}
rows=json.load(sys.stdin).get('resource_changes',[])
counts=collections.Counter()
for row in rows:
    actions=row['change']['actions'];t=row['type']
    if t not in paid: continue
    if 'delete' in actions: sys.exit('STOP: paid resource deletion/replacement; ask Aziz for a new yes after showing this plan')
    if 'create' in actions: counts[t]+=1
expected={'1':{'aws_eks_cluster':1}, '2':{'aws_nat_gateway':1,'aws_eip':1,'aws_eks_node_group':1}, '3':{}}[sys.argv[1]]
if counts and dict(counts)!=expected:
    sys.exit('STOP: paid resource counts differ from the approved build; ask Aziz for a new yes after showing this plan')
PY
)" "$number"
}
plan_cost() {
    terraform -chdir="$TF_ROOT/$1" show -json "$2" | python3 -c "$(cat <<'PY'
import collections,json,sys
from decimal import Decimal
rows=json.load(sys.stdin).get("resource_changes",[])
creates=[row for row in rows if "create" in row["change"]["actions"]]
counts=collections.Counter(row["type"] for row in creates)
# The approved Singapore rates include the managed node's fixed 50 GB root disk.
rates={"aws_eks_cluster":Decimal("0.10"),"aws_nat_gateway":Decimal("0.059"),
       "aws_eip":Decimal("0.005"),"aws_eks_node_group":Decimal("0.2112")+50*Decimal("0.096")/720}
labels={"aws_eks_cluster":"EKS control plane","aws_nat_gateway":"NAT gateway",
        "aws_eip":"public IPv4 address","aws_eks_node_group":"worker node group with a 50 GB root disk"}
if any(counts[kind] for kind in ("aws_instance","aws_lb","aws_ebs_volume")):
    sys.exit("STOP: saved plan contains an unexpected paid type; review the plan before pricing")
total=sum((rates[kind]*counts[kind] for kind in rates),Decimal(0))
traefik=any(row.get("address")=="helm_release.traefik" for row in creates)
parts=[]
paid=[f"{counts[kind]} {labels[kind]}" for kind in rates if counts[kind]]
if paid: parts.append("creates "+", ".join(paid))
if traefik:
    parts.append("controller creates 1 network load balancer and 1 public IPv4 address")
    total+=Decimal("0.0252")+Decimal("0.005")
free=len(creates)-sum(counts[kind] for kind in rates)
if free: parts.append(f"creates {free} resource"+("" if free==1 else "s")+" without hourly charges")
if not paid and not traefik: parts.append("creates nothing paid")
amount="0" if total==0 else format(total.quantize(Decimal("0.001")),"f")
parts.append(f"about USD {amount}/hour extra")
if counts["aws_nat_gateway"]: parts.append("NAT traffic USD 0.059/GB")
if traefik: parts.append("load balancer capacity units extra")
print("; ".join(parts))
PY
)"
}
capture_node_tags() {
    local group asg lt tags
    group=$(aws eks describe-nodegroup --cluster-name ooh-aws --nodegroup-name main --query 'nodegroup.resources.autoScalingGroups[0].name' --output text)
    asg=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$group" --output json)
    tags=$(jq '.AutoScalingGroups[0].Tags' <<< "$asg")
    printf 'Auto Scaling group tags: %s\n' "${tags//"$AWS_ACCOUNT"/<account>}"
    lt=$(jq -r '.AutoScalingGroups[0] | .LaunchTemplate.LaunchTemplateId // .MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification.LaunchTemplateId // empty' <<< "$asg")
    [[ -n $lt ]] || { printf 'FAIL: no launch template found on the Auto Scaling group\n'; stop 'cannot record the launch template; ask Aziz before continuing'; }
    save_setting EKS_LT_ID "$lt"
    tags=$(aws ec2 describe-launch-templates --launch-template-ids "$lt" --query 'LaunchTemplates[0].Tags' --output json)
    printf 'Launch template tags: %s\n' "${tags//"$AWS_ACCOUNT"/<account>}"
    if ! jq -e 'any(.[]; .Key == "eks:cluster-name" and .Value == "ooh-aws")' >/dev/null <<< "$tags"; then
        printf '%s\n' 'FAIL: launch template has no eks:cluster-name=ooh-aws tag; Claude must ask Aziz whether the destroy sweep should also check EKS_LT_ID while the build continues; copy costs about USD 0.42/hour; a launch template bills nothing'
    fi
}
cluster_main() {
    aws_setup
    check_signin
    check_age
    AWS_PLANS=("$AWS_CACHE/cluster-1.tfplan" "$AWS_CACHE/cluster-2.tfplan" "$AWS_CACHE/addons.tfplan")
    trap cleanup_plans EXIT
    price_table
    init_root cluster
    terraform -chdir="$TF_ROOT/cluster" plan -input=false -target=aws_eks_cluster.main -out="${AWS_PLANS[0]}"
    show_plan cluster "${AWS_PLANS[0]}"
    local first entries access resources cost
    first=$(terraform -chdir="$TF_ROOT/cluster" show -json "${AWS_PLANS[0]}")
    if jq -e 'any(.resource_changes[]?; .type == "aws_nat_gateway" or .type == "aws_eip")' >/dev/null <<< "$first"; then stop 'control-plane plan contains a NAT gateway or public address; nothing was applied'; fi
    paid_guard 1 cluster "${AWS_PLANS[0]}"
    resources=$(jq -r '.resource_changes[]? | "\(.address): \(.change.actions | join(", ")); \(if .type == "aws_eks_cluster" and (.change.actions | index("create") != null) then "USD 0.10/hour extra" else "USD 0/hour extra" end)"' <<< "$first")
    printf '%s\n' "$resources"
    cost=$(plan_cost cluster "${AWS_PLANS[0]}")
    printf 'Saved plan: %s\n' "$cost"
    confirm "Type yes to apply this saved plan ($cost)"
    apply_plan cluster "${AWS_PLANS[0]}"
    EKS_ENDPOINT=$(terraform -chdir="$TF_ROOT/cluster" output -raw endpoint)
    save_setting EKS_ENDPOINT "$EKS_ENDPOINT"
    install -d -m 700 "$HOME/.kube"
    aws eks update-kubeconfig --name ooh-aws --kubeconfig "$KUBECONFIG" >/dev/null
    chmod 600 "$KUBECONFIG"
    check_kube
    if ! kubectl get --raw /readyz || ! access=$(kubectl auth can-i '*' '*' --all-namespaces) || [[ $access != yes ]] || ! kubectl get namespaces; then
        stop 'root cluster-admin access unproven; do not build nodes; ask Aziz for a new decision and destroy the control plane with install/85-aws-destroy.sh'
    fi
    entries=$(aws eks list-access-entries --cluster-name ooh-aws --output json)
    printf '%s\n' "${entries//"$AWS_ACCOUNT"/<account>}"
    terraform -chdir="$TF_ROOT/cluster" plan -input=false -out="${AWS_PLANS[1]}"
    show_plan cluster "${AWS_PLANS[1]}"
    paid_guard 2 cluster "${AWS_PLANS[1]}"
    check_ebs_schema
    # Regional build suffixes are not all listed on AWS's public version pages.
    local addon version available
    while read -r addon version; do
        available=$(aws eks describe-addon-versions --addon-name "$addon" --kubernetes-version 1.36 --output json)
        jq -e --arg v "$version" 'any(.addons[].addonVersions[]; .addonVersion == $v)' >/dev/null <<< "$available" || stop "$addon pinned version $version is not offered for EKS 1.36 in Singapore; ask the spec author"
    done <<'VERSIONS'
vpc-cni v1.22.4-eksbuild.14
kube-proxy v1.36.0-eksbuild.65
eks-pod-identity-agent v1.4.1-eksbuild.3
coredns v1.14.7-eksbuild.35
aws-ebs-csi-driver v1.68.0-eksbuild.1
VERSIONS
    cost=$(plan_cost cluster "${AWS_PLANS[1]}")
    printf 'Saved plan: %s\n' "$cost"
    confirm "Type yes to apply this saved plan ($cost)"
    apply_plan cluster "${AWS_PLANS[1]}"
    kubectl wait --for=condition=Ready nodes --all --timeout=600s
    capture_node_tags
    init_root addons
    terraform -chdir="$TF_ROOT/addons" plan -input=false -out="${AWS_PLANS[2]}"
    show_plan addons "${AWS_PLANS[2]}"
    paid_guard 3 addons "${AWS_PLANS[2]}"
    cost=$(plan_cost addons "${AWS_PLANS[2]}")
    printf 'Saved plan: %s\n' "$cost"
    confirm "Type yes to apply this saved plan ($cost)"
    apply_plan addons "${AWS_PLANS[2]}"
    kubectl -n kube-system wait --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}' service/traefik --timeout=600s
    local hostname
    hostname=$(kubectl -n kube-system get service traefik -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
    save_setting LB_HOSTNAME "$hostname"
    printf 'Add CNAME records (TTL 300):\nharness.aws.faysalaziz.com -> %s\nadmin.aws.faysalaziz.com -> %s\nauth.aws.faysalaziz.com -> %s\n' "$hostname" "$hostname" "$hostname"
    printf 'DONE\n'
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then cluster_main "$@"; fi
