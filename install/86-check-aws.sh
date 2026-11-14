#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
# shellcheck source=install/85-aws-destroy.sh
source "$(dirname "${BASH_SOURCE[0]}")/85-aws-destroy.sh"
aws_check() {
    local label=$1
    shift
    if "$@" > "$AWS_CHECK_DIR/result" 2>&1; then printf 'PASS: %s\n' "$label";
    else
        printf 'FAIL: %s\n' "$label"
        if [[ $1 == check_running_inventory ]]; then
            while IFS= read -r line; do [[ $line != FAIL:* ]] || printf '%s\n' "$line"; done < "$AWS_CHECK_DIR/result"
        fi
        AWS_FAILURES=$((AWS_FAILURES + 1))
    fi
}
check_cluster() {
    local cluster
    cluster=$(aws eks describe-cluster --name ooh-aws --output json) || return
    jq -e '.cluster | .status == "ACTIVE" and .version == "1.36" and .resourcesVpcConfig.endpointPrivateAccess and .resourcesVpcConfig.endpointPublicAccess and (.resourcesVpcConfig.publicAccessCidrs == ["143.198.221.2/32"])' <<< "$cluster"
}
check_node() {
    local nodes id instance private
    nodes=$(kubectl get nodes -o json) || return
    jq -e '.items | length == 1 and all(.[]; .metadata.labels["node.kubernetes.io/instance-type"] == "t3.xlarge" and .metadata.labels["topology.kubernetes.io/zone"] == "ap-southeast-1a" and any(.status.conditions[]; .type == "Ready" and .status == "True"))' >/dev/null <<< "$nodes" || return
    id=$(jq -r '.items[0].spec.providerID | split("/")[-1]' <<< "$nodes")
    instance=$(aws ec2 describe-instances --instance-ids "$id" --output json) || return
    private=$(terraform -chdir="$TF_ROOT/cluster" output -raw private_subnet_a_id) || return
    jq -e --arg subnet "$private" '.Reservations[0].Instances[0] | .SubnetId == $subnet and .InstanceType == "t3.xlarge" and .PublicIpAddress == null and all(.NetworkInterfaces[]; .Association.PublicIp == null)' <<< "$instance"
}
check_addons() {
    local addon data
    for addon in vpc-cni kube-proxy eks-pod-identity-agent coredns aws-ebs-csi-driver; do
        data=$(aws eks describe-addon --cluster-name ooh-aws --addon-name "$addon" --output json) || return
        jq -e '.addon.status == "ACTIVE"' >/dev/null <<< "$data" || return
    done
}
load_balancer() {
    local service rows
    service=$(kubectl -n kube-system get service traefik -o json) || return
    [[ $(jq '.status.loadBalancer.ingress | length' <<< "$service") == 1 ]] || return 1
    [[ $(jq -r '.status.loadBalancer.ingress[0].hostname' <<< "$service") == "$LB_HOSTNAME" ]] || return 1
    rows=$(aws elbv2 describe-load-balancers --output json) || return
    jq -e --arg host "$LB_HOSTNAME" '[.LoadBalancers[] | select(.DNSName == $host)] | length == 1' >/dev/null <<< "$rows" || return
    jq --arg host "$LB_HOSTNAME" '.LoadBalancers[] | select(.DNSName == $host)' <<< "$rows"
}
check_frontdoor() {
    local dep lb targets arn attrs
    for dep in traefik aws-load-balancer-controller; do
        kubectl -n kube-system rollout status "deployment/$dep" --timeout=60s || return
    done
    lb=$(load_balancer) || return
    jq -e '.Type == "network" and .Scheme == "internet-facing" and (.AvailabilityZones | length == 1) and .AvailabilityZones[0].ZoneName == "ap-southeast-1a"' >/dev/null <<< "$lb" || return
    arn=$(jq -r '.LoadBalancerArn' <<< "$lb")
    targets=$(aws elbv2 describe-target-groups --load-balancer-arn "$arn" --output json) || return
    [[ $(jq '.TargetGroups | length' <<< "$targets") -gt 0 ]] || return 1
    while IFS= read -r arn; do
        attrs=$(aws elbv2 describe-target-group-attributes --target-group-arn "$arn" --output json) || return
        jq -e 'any(.Attributes[]; .Key == "proxy_protocol_v2.enabled" and .Value == "true")' >/dev/null <<< "$attrs" || return
    done < <(jq -r '.TargetGroups[].TargetGroupArn' <<< "$targets")
}
check_storage() {
    local sc pv volume id
    sc=$(kubectl get storageclass ooh-gp3 -o json) || return
    jq -e '.provisioner == "ebs.csi.aws.com" and .parameters.type == "gp3" and .parameters.encrypted == "true" and .volumeBindingMode == "WaitForFirstConsumer" and .reclaimPolicy == "Delete" and .allowVolumeExpansion == true' >/dev/null <<< "$sc" || return
    pv=$(kubectl get pv -o json) || return
    jq -e 'all(.items[] | select(.status.phase == "Bound"); .spec.storageClassName == "ooh-gp3" and .spec.csi.driver == "ebs.csi.aws.com")' >/dev/null <<< "$pv" || return
    while IFS= read -r id; do
        volume=$(aws ec2 describe-volumes --volume-ids "$id" --output json) || return
        jq -e '.Volumes[0] | .Encrypted and .VolumeType == "gp3" and ((.Tags | map({key:.Key,value:.Value}) | from_entries) as $t | $t["ooh-stage"] == "4b" and $t.stage == "4b" and $t.project == "open-office-harness" and $t["managed-by"] == "terraform" and $t["kubernetes.io/cluster/ooh-aws"] == "owned")' >/dev/null <<< "$volume" || return
    done < <(jq -r '.items[] | select(.status.phase == "Bound") | .spec.csi.volumeHandle' <<< "$pv")
}
check_names() {
    local name cname
    for name in harness admin auth; do
        cname=$(dig +short CNAME "$name.aws.faysalaziz.com") || return
        [[ ${cname%.} == "$LB_HOSTNAME" ]] || return 1
    done
}
check_address() {
    local marker logs
    marker=$(cat /proc/sys/kernel/random/uuid)
    curl --silent --show-error --max-time 30 -H "X-Ooh-Marker: $marker" "https://harness.aws.faysalaziz.com/ooh-address-check-$marker" -o /dev/null || return
    local deadline=$((SECONDS + 30))
    while (( SECONDS < deadline )); do
        logs=$(kubectl -n kube-system logs -l app.kubernetes.io/name=traefik --since=2m --tail=-1) || return
        if jq -Rse --arg marker "$marker" 'split("\n") | map(fromjson? | select(."request_X-Ooh-Marker" == $marker)) | length > 0 and all(.[]; .ClientHost == "143.198.221.2")' >/dev/null <<< "$logs"; then return; fi
        sleep 2
    done
    return 1
}
check_state() {
    local version encryption public
    version=$(aws s3api get-bucket-versioning --bucket "$AWS_BUCKET" --output json) || return
    encryption=$(aws s3api get-bucket-encryption --bucket "$AWS_BUCKET" --output json) || return
    public=$(aws s3api get-public-access-block --bucket "$AWS_BUCKET" --output json) || return
    jq -e '.Status == "Enabled"' >/dev/null <<< "$version" || return
    jq -e '.ServerSideEncryptionConfiguration.Rules | any(.[]; .ApplyServerSideEncryptionByDefault.SSEAlgorithm == "AES256")' >/dev/null <<< "$encryption" || return
    jq -e '.PublicAccessBlockConfiguration | .BlockPublicAcls and .IgnorePublicAcls and .BlockPublicPolicy and .RestrictPublicBuckets' >/dev/null <<< "$public" || return
    [[ $(awk '/^use_lockfile *= *true$/ {print "yes"}' "$AWS_LOCAL/aws-backend.hcl") == yes ]] || return 1
    terraform -chdir="$TF_ROOT/cluster" plan -input=false -lock-timeout=0s >/dev/null
}
check_budget() {
    local budget notifications
    budget=$(aws budgets describe-budget --account-id "$AWS_ACCOUNT" --budget-name ooh-aws-copy --output json) || return
    notifications=$(aws budgets describe-notifications-for-budget --account-id "$AWS_ACCOUNT" --budget-name ooh-aws-copy --output json) || return
    jq -e '.Budget | .BudgetType == "COST" and (.BudgetLimit.Amount | tonumber) == 40 and .BudgetLimit.Unit == "USD" and .TimeUnit == "MONTHLY"' >/dev/null <<< "$budget" || return
    jq -e 'all(.Notifications[]; .ComparisonOperator == "GREATER_THAN") and ([.Notifications[] | [.NotificationType,.Threshold,(.ThresholdType | if . == null then "PERCENTAGE" else . end)]] | sort == ([["ACTUAL",50,"PERCENTAGE"],["ACTUAL",80,"PERCENTAGE"],["ACTUAL",100,"PERCENTAGE"],["FORECASTED",100,"PERCENTAGE"]] | sort))' >/dev/null <<< "$notifications" || return
    local type threshold threshold_type notification subscribers
    [[ -n ${BUDGET_EMAIL:-} ]] || return 1
    while read -r type threshold threshold_type; do
        notification="NotificationType=$type,ComparisonOperator=GREATER_THAN,Threshold=$threshold"
        [[ $threshold_type != PERCENTAGE ]] || notification+=",ThresholdType=PERCENTAGE"
        subscribers=$(aws budgets describe-subscribers-for-notification --account-id "$AWS_ACCOUNT" --budget-name ooh-aws-copy --notification "$notification" --output json) || return
        jq -e --arg email "$BUDGET_EMAIL" '.Subscribers == [{SubscriptionType:"EMAIL",Address:$email}]' >/dev/null <<< "$subscribers" || return
    done < <(jq -r '.Notifications[] | [.NotificationType,.Threshold,(.ThresholdType | if . == null then "OMITTED" else . end)] | @tsv' <<< "$notifications")
}
check_running_inventory() {
    local group asg lt
    aws_inventory > "$AWS_CHECK_DIR/inventory.json" || return
    terraform -chdir="$TF_ROOT/cluster" show -json > "$AWS_CHECK_DIR/cluster.json" || return
    init_root addons >/dev/null || return
    terraform -chdir="$TF_ROOT/addons" show -json > "$AWS_CHECK_DIR/addons.json" || return
    kubectl get nodes -o json > "$AWS_CHECK_DIR/nodes.json" || return
    kubectl get pv -o json > "$AWS_CHECK_DIR/pv.json" || return
    load_balancer > "$AWS_CHECK_DIR/lb.json" || return
    aws eks describe-cluster --name ooh-aws > "$AWS_CHECK_DIR/eks.json" || return
    group=$(aws eks describe-nodegroup --cluster-name ooh-aws --nodegroup-name main --query 'nodegroup.resources.autoScalingGroups[0].name' --output text) || return
    asg=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$group" --output json) || return
    lt=$(jq -r '.AutoScalingGroups[0] | .LaunchTemplate.LaunchTemplateId // .MixedInstancesPolicy.LaunchTemplate.LaunchTemplateSpecification.LaunchTemplateId // empty' <<< "$asg")
    [[ -n $lt ]] || { printf 'FAIL: no launch template found on the Auto Scaling group\n'; return 1; }
    printf '%s' "$asg" > "$AWS_CHECK_DIR/asg.json"
    python3 - "$AWS_CHECK_DIR" "$lt" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]);lt=sys.argv[2]
def read(n): return json.loads((p/(n+'.json')).read_text())
ids=set()
def walk(x):
    if isinstance(x,dict):
        for v in x.values(): walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
    elif isinstance(x,str): ids.add(x)
for n in ['cluster','addons']: walk(read(n).get('values',{}))
nodeids={n['spec']['providerID'].split('/')[-1] for n in read('nodes')['items']}
volumes={pv['spec'].get('csi',{}).get('volumeHandle') for pv in read('pv')['items']}
lb=read('lb');asg=read('asg')['AutoScalingGroups'][0];eks=read('eks')['cluster']
fail=[]
for row in read('inventory'):
    r=row['raw'];kind=row['type'];identity=row['id'];ts=row['tags']
    if row['region'] not in ['ap-southeast-1','global']:
        fail.append(row);continue
    allowed=identity in ids or row['arn'] in ids
    if row['region']=='global':
        if not allowed: fail.append(row)
        continue
    if kind=='volume':
        allowed |= identity in volumes or any(a.get('InstanceId') in nodeids and a.get('Device') in ['/dev/xvda','/dev/sda1'] for a in r.get('Attachments',[]))
    if ts.get('elbv2.k8s.aws/cluster')=='ooh-aws':
        allowed |= (kind=='lb' and identity==lb['LoadBalancerArn']) or (kind=='target' and lb['LoadBalancerArn'] in r.get('LoadBalancerArns',[])) or (kind=='sg' and (identity in lb.get('SecurityGroups',[]) or (ts.get('elbv2.k8s.aws/resource')=='backend-sg' and r.get('VpcId')==eks['resourcesVpcConfig']['vpcId'])))
    if kind=='eni':
        allowed |= r.get('Attachment',{}).get('InstanceId') in nodeids or ts.get('cluster.k8s.amazonaws.com/name')=='ooh-aws'
        # NAT interfaces are explicitly named by the Terraform-owned NAT gateway.
        nats=[n for n in read('inventory') if n['type']=='nat' and (n['id'] in ids or n['arn'] in ids)]
        allowed |= any(identity==a.get('NetworkInterfaceId') for n in nats for a in n['raw'].get('NatGatewayAddresses',[]))
        lbpath=lb['LoadBalancerArn'].split('loadbalancer/')[-1]
        allowed |= r.get('Description')=='ELB '+lbpath
        allowed |= r.get('RequesterManaged',False) and r.get('Description')=='Amazon EKS ooh-aws' and any(g['GroupId']==eks['resourcesVpcConfig']['clusterSecurityGroupId'] for g in r.get('Groups',[]))
    if kind=='sg': allowed |= ts.get('aws:eks:cluster-name')=='ooh-aws'
    if kind=='asg': allowed |= identity==asg['AutoScalingGroupName']
    if kind=='instance': allowed |= identity in {i['InstanceId'] for i in asg['Instances']}
    if kind=='lt': allowed |= identity==lt
    if not allowed: fail.append(row)
for r in fail: print(f"FAIL: unexpected {r['region']} {r['type']} {r['id']}")
sys.exit(bool(fail))
PY
}
check_images() {
    local deployments
    deployments=$(kubectl -n ooh-apps get deployments -o json) || return
    jq -e '["audit-writer","admin-console","control-centre","cost-meter","harness-api","model-gateway","safety-watcher","slides-worker","workspace"] as $expected | all(.items[].spec.template.spec.initContainers[]?; .image | endswith(":7c721a4de601")) and ([.items[].spec.template.spec.containers[].image] as $images | ($images | length) == 9 and all($expected[]; . as $name | $images | index("ghcr.io/frozenfussion/ooh-" + $name + ":7c721a4de601") != null))' <<< "$deployments"
}
check_private_services() {
    local services ingresses
    services=$(kubectl get services -A -o json) || return
    ingresses=$(kubectl get ingresses -A -o json) || return
    jq -e 'all(.items[]; .spec.type != "LoadBalancer" or (.metadata.namespace == "kube-system" and .metadata.name == "traefik"))' >/dev/null <<< "$services" || return
    jq -e 'all(.items[]; all((.spec.defaultBackend.service.name?, .spec.rules[]?.http.paths[]?.backend.service.name?); . != "model-gateway"))' <<< "$ingresses"
}
replace_node() {
    local nodes old instance started deadline current volumes pods old_disk old_disks
    check_age
    nodes=$(kubectl get nodes -o json)
    [[ $(jq '.items|length' <<< "$nodes") == 1 ]] || stop 'replacement test needs exactly one node'
    old=$(jq -r '.items[0].spec.providerID | split("/")[-1]' <<< "$nodes")
    instance=$(aws ec2 describe-instances --instance-ids "$old" --output json)
    old_disk=$(jq -r '.Reservations[0].Instances[0] | .RootDeviceName as $root | .BlockDeviceMappings[] | select(.DeviceName == $root) | .Ebs.VolumeId' <<< "$instance")
    [[ -n $old_disk ]] || stop 'old node root disk could not be identified'
    confirm 'Type yes to replace the AWS worker node (copy stays about USD 0.42/hour; image pull about USD 0.30)'
    started=$(date -u +%s)
    aws ec2 terminate-instances --instance-ids "$old" >/dev/null
    deadline=$((SECONDS + 1500))
    while (( SECONDS < deadline )); do
        current=$(kubectl get nodes -o json)
        pods=$(kubectl get pods -A -o json)
        instance=$(aws eks describe-nodegroup --cluster-name ooh-aws --nodegroup-name main --query 'nodegroup.status' --output text)
        if [[ $instance == ACTIVE ]] && jq -e --arg old "$old" '.items | length == 1 and all(.[]; (.spec.providerID | endswith($old) | not) and any(.status.conditions[]; .type == "Ready" and .status == "True"))' >/dev/null <<< "$current" && jq -e 'all(.items[] | select(any(.spec.volumes[]?; has("persistentVolumeClaim"))); .status.phase == "Running")' >/dev/null <<< "$pods"; then
            volumes=$(aws ec2 describe-volumes --filters Name=tag:stage,Values=4b Name=status,Values=available --output json)
            old_disks=$(aws ec2 describe-volumes --filters "Name=volume-id,Values=$old_disk" --output json)
            if [[ $(jq '.Volumes | length' <<< "$old_disks") == 0 ]] && jq -e 'all(.Volumes[]; any(.Tags[]; .Key == "ooh-stage" and .Value == "4b"))' >/dev/null <<< "$volumes"; then
                printf 'PASS: node replacement and old root disk removal in %s seconds\n' "$(( $(date -u +%s) - started ))"
                OOH_TARGET=aws "$AWS_ROOT/install/40-check-platform.sh"
                OOH_TARGET=aws "$AWS_ROOT/install/62-check-control-centre.sh"
                return
            fi
        fi
        sleep 10
    done
    stop 'node replacement or old root disk cleanup exceeded 25 minutes; inspect the node group and EBS disks'
}
check_main() {
    local mode=${1:-}
    [[ $# -le 1 && ( -z $mode || $mode == --replace-node ) ]] || stop 'use install/86-check-aws.sh [--replace-node]'
    aws_setup
    AWS_PLANS=()
    trap 'cleanup_plans; [[ -z ${AWS_CHECK_DIR:-} ]] || rm -rf "$AWS_CHECK_DIR"' EXIT
    AWS_CHECK_DIR=$(mktemp -d "$AWS_CACHE/check.XXXXXX")
    AWS_FAILURES=0
    check_signin
    printf 'PASS: caller is the state bucket account\n'
    check_kube
    init_root cluster > "$AWS_CHECK_DIR/init" 2>&1
    [[ $mode != --replace-node ]] || replace_node
    aws_check 'EKS version, status and locked API endpoint' check_cluster
    aws_check 'one Ready private t3.xlarge node in zone a' check_node
    aws_check 'five managed add-ons ACTIVE' check_addons
    aws_check 'controllers Ready, one public NLB with proxy protocol' check_frontdoor
    aws_check 'gp3 StorageClass, encrypted and tagged bound disks' check_storage
    aws_check 'three CNAME records point at the load balancer' check_names
    aws_check 'visitor address reaches Traefik with the marker' check_address
    aws_check 'state bucket protections and Terraform locking' check_state
    aws_check 'USD 40 budget and four notifications' check_budget
    aws_check 'all stage resources belong to this running copy' check_running_inventory
    # Item 11 must expose each leftover ID and the missing-template failure.
    aws_check 'all nine deployments use the class-start images' check_images
    aws_check 'only Traefik is public; Model Gateway has no Ingress' check_private_services
    printf 'INFO: confirm the budget email in the budget recipient inbox; otherwise no alerts arrive\n'
    (( AWS_FAILURES == 0 )) || stop "$AWS_FAILURES AWS checks failed; investigate and retry install/86-check-aws.sh"
    printf 'DONE\n'
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then check_main "$@"; fi
