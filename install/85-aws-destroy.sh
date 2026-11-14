#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
# shellcheck source=install/81-aws-bootstrap.sh
source "$(dirname "${BASH_SOURCE[0]}")/81-aws-bootstrap.sh"
# Shared by the destroy sweep and check 86; inventory is read-only.
aws_inventory() {
python3 - <<'PY'
import json,subprocess,sys
REGION='ap-southeast-1'
MARKERS={'stage':'4b','ooh-stage':'4b','elbv2.k8s.aws/cluster':'ooh-aws','kubernetes.io/cluster/ooh-aws':'owned','cluster.k8s.amazonaws.com/name':'ooh-aws','eks:cluster-name':'ooh-aws'}
def call(region,service,operation,**args):
    cmd=['aws','--region',region,service,operation,'--output','json']
    for k,v in args.items():
        cmd+=['--'+k.replace('_','-')]
        cmd+=v if isinstance(v,list) else [v]
    result=subprocess.run(cmd,text=True,capture_output=True)
    if result.returncode:
        sys.exit(f'STOP: inventory failed for {service} {operation} in {region}; sign in again or check permissions and retry')
    return json.loads(result.stdout)
def tags(raw):
    ts=raw.get('Tags',raw.get('tags',raw.get('TagSet',{}))) or {}
    return ts if isinstance(ts,dict) else {t.get('Key',t.get('TagKey')):t.get('Value',t.get('TagValue')) for t in ts}
rows=[]
def add(region,kind,raw,idkey,arnkey=None,name=None,force=False):
    ts=tags(raw);identity=raw[idkey]
    named=name or str(raw.get('Name',raw.get('name','')))
    if force or any(ts.get(k)==v for k,v in MARKERS.items()) or 'ooh-aws' in named:
        rows.append(dict(region=region,type=kind,id=identity,arn=raw.get(arnkey,identity) if arnkey else identity,tags=ts,raw=raw))
regions=[r['RegionName'] for r in call(REGION,'ec2','describe-regions')['Regions']]
for region in regions:
    specs=[('instance','describe-instances','Reservations','InstanceId'),('volume','describe-volumes','Volumes','VolumeId'),('nat','describe-nat-gateways','NatGateways','NatGatewayId'),('eip','describe-addresses','Addresses','AllocationId'),('eni','describe-network-interfaces','NetworkInterfaces','NetworkInterfaceId'),('sg','describe-security-groups','SecurityGroups','GroupId'),('lt','describe-launch-templates','LaunchTemplates','LaunchTemplateId'),('vpc','describe-vpcs','Vpcs','VpcId'),('subnet','describe-subnets','Subnets','SubnetId'),('route-table','describe-route-tables','RouteTables','RouteTableId'),('igw','describe-internet-gateways','InternetGateways','InternetGatewayId')]
    for kind,op,key,idkey in specs:
        rawrows=call(region,'ec2',op)[key]
        if kind=='instance': rawrows=[i for r in rawrows for i in r['Instances']]
        for row in rawrows:
            if kind=='instance' and row['State']['Name']=='terminated': continue
            if kind=='nat' and row['State']=='deleted': continue
            add(region,kind,row,idkey,name=row.get('LaunchTemplateName',row.get('GroupName','')))
    for kind,op,key,idkey in [('lb','describe-load-balancers','LoadBalancers','LoadBalancerArn'),('target','describe-target-groups','TargetGroups','TargetGroupArn')]:
        for row in call(region,'elbv2',op)[key]:
            row['Tags']=call(region,'elbv2','describe-tags',resource_arns=[row[idkey]])['TagDescriptions'][0]['Tags']
            add(region,kind,row,idkey,name=row.get('LoadBalancerName',row.get('TargetGroupName','')))
    for row in call(region,'autoscaling','describe-auto-scaling-groups')['AutoScalingGroups']:
        add(region,'asg',row,'AutoScalingGroupName','AutoScalingGroupARN')
    if 'ooh-aws' in call(region,'eks','list-clusters')['clusters']:
        row=call(region,'eks','describe-cluster',name='ooh-aws')['cluster']
        add(region,'eks',row,'name','arn',force=True)
    for row in call(region,'logs','describe-log-groups')['logGroups']:
        arn=row.get('logGroupArn',row['arn'].removesuffix(':*'))
        row['tags']=call(region,'logs','list-tags-for-resource',resource_arn=arn).get('tags',{})
        add(region,'log',row,'logGroupName','arn',force=row['logGroupName'].startswith('/aws/eks/ooh-aws/'))
    for item in call(region,'kms','list-keys')['Keys']:
        key=call(region,'kms','describe-key',key_id=item['KeyId'])['KeyMetadata']
        if key['KeyManager']!='CUSTOMER': continue
        key['Tags']=call(region,'kms','list-resource-tags',key_id=item['KeyId'])['Tags']
        add(region,'kms',key,'KeyId','Arn')
for kind,op,key,idkey,arnkey in [('role','list-roles','Roles','RoleName','Arn'),('policy','list-policies','Policies','PolicyName','Arn'),('profile','list-instance-profiles','InstanceProfiles','InstanceProfileName','Arn')]:
    args={'scope':'Local'} if kind=='policy' else {}
    for row in call(REGION,'iam',op,**args)[key]:
        if row[idkey].startswith('ooh-aws'):
            add('global',kind,row,idkey,arnkey,force=True)
json.dump(rows,sys.stdout)
PY
}
sweep_empty() {
    local inventory deadline row transitional
    deadline=$((SECONDS + 600))
    while true; do
        inventory=$(aws_inventory) || stop 'resource inventory failed; retry install/85-aws-destroy.sh --sweep-only'
        [[ $inventory == '[]' ]] && { printf 'PASS: no AWS copy resources remain (state bucket and budget kept unless --all)\n'; return; }
        transitional=$(jq '[.[] | select((.type == "instance" and .raw.State.Name == "shutting-down") or (.type == "nat" and .raw.State == "deleting") or (.type == "volume" and .raw.State == "deleting") or (.type == "eks" and .raw.status == "DELETING"))] | length' <<< "$inventory")
        if (( transitional > 0 && SECONDS < deadline )); then sleep 10; continue; fi
        while IFS= read -r row; do printf 'FAIL: leftover %s\n' "$row"; done < <(jq -r '.[] | "\(.region) \(.type) \(.id)"' <<< "$inventory")
        stop 'AWS copy resources remain; use the IDs above to investigate, then rerun install/85-aws-destroy.sh'
    done
}
cluster_load_balancers() {
    local balancers arn tags result='[]' row
    balancers=$(aws elbv2 describe-load-balancers --output json)
    while IFS= read -r arn; do
        tags=$(aws elbv2 describe-tags --resource-arns "$arn" --output json)
        if jq -e 'any(.TagDescriptions[].Tags[]; .Key == "elbv2.k8s.aws/cluster" and .Value == "ooh-aws")' >/dev/null <<< "$tags"; then
            row=$(jq --arg arn "$arn" '.LoadBalancers[] | select(.LoadBalancerArn == $arn) | {ARN:.LoadBalancerArn,Name:.LoadBalancerName,DNS:.DNSName}' <<< "$balancers")
            result=$(jq --argjson row "$row" '. + [$row]' <<< "$result")
        fi
    done < <(jq -r '.LoadBalancers[].LoadBalancerArn' <<< "$balancers")
    printf '%s\n' "$result"
}
wait_no_lb() {
    local deadline=$((SECONDS + 600)) rows
    while true; do
        rows=$(cluster_load_balancers)
        [[ $(jq 'length' <<< "$rows") != 0 ]] || return 0
        (( SECONDS < deadline )) || stop 'load balancer still exists; inspect controller logs and rerun install/85-aws-destroy.sh'
        sleep 10
    done
}
wait_no_controller_resources() {
    local deadline=$((SECONDS + 600)) groups arn tags security_groups remaining
    while true; do
        remaining=false
        groups=$(aws --region ap-southeast-1 elbv2 describe-target-groups --output json)
        while IFS= read -r arn; do
            tags=$(aws --region ap-southeast-1 elbv2 describe-tags --resource-arns "$arn" --output json) || { remaining=true; continue; }
            if jq -e 'any(.TagDescriptions[].Tags[]; .Key == "elbv2.k8s.aws/cluster" and .Value == "ooh-aws")' >/dev/null <<< "$tags"; then remaining=true; fi
        done < <(jq -r '.TargetGroups[].TargetGroupArn' <<< "$groups")
        security_groups=$(aws --region ap-southeast-1 ec2 describe-security-groups --filters 'Name=tag:elbv2.k8s.aws/cluster,Values=ooh-aws' --output json)
        if jq -e '.SecurityGroups | length > 0' >/dev/null <<< "$security_groups"; then remaining=true; fi
        $remaining || return 0
        (( SECONDS < deadline )) || stop 'controller target groups or security groups still exist; inspect controller logs and rerun install/85-aws-destroy.sh'
        sleep 10
    done
}
wait_no_data_volumes() {
    local deadline=$((SECONDS + 600)) volumes
    while true; do
        volumes=$(aws ec2 describe-volumes --output json)
        if jq -e 'all(.Volumes[]; (.Tags // [] | map({key:.Key,value:.Value}) | from_entries) as $t | ($t["ooh-stage"] != "4b" and ($t["kubernetes.io/cluster/ooh-aws"] != "owned" or $t["ebs.csi.aws.com/cluster"] != "true")))' >/dev/null <<< "$volumes"; then return; fi
        (( SECONDS < deadline )) || stop 'data volumes still exist; inspect EBS CSI logs and rerun install/85-aws-destroy.sh'
        sleep 10
    done
}
clean_kubernetes() {
    local ns objects pods pod deadline crd
    kubectl -n kube-system delete service traefik --ignore-not-found --timeout=600s
    wait_no_lb
    wait_no_controller_resources
    kubectl -n ooh-apps delete deployments --all --ignore-not-found --timeout=600s
    # A missing CRD on a partial build is not a cleanup failure.
    for objects in kafkatopics.kafka.strimzi.io kafkausers.kafka.strimzi.io kafkas.kafka.strimzi.io clusters.postgresql.cnpg.io keycloaks.k8s.keycloak.org; do
        crd=$(kubectl get crd "$objects" --ignore-not-found -o name)
        if [[ -n $crd ]]; then
            kubectl -n ooh-platform delete "$objects" --all --ignore-not-found --timeout=600s
        fi
    done
    for ns in ooh-apps ooh-platform; do
        pods=$(kubectl -n "$ns" get pods -o json)
        while IFS= read -r pod; do
            [[ -z $pod ]] || kubectl -n "$ns" delete pod "$pod" --ignore-not-found --timeout=600s
        done < <(jq -r '.items[] | select((.metadata.ownerReferences // [] | length) == 0) | .metadata.name' <<< "$pods")
    done
    deadline=$((SECONDS + 600))
    while true; do
        pods=$(kubectl get pods -A -o json)
        if jq -e 'all(.items[] | select(.metadata.namespace == "ooh-apps" or .metadata.namespace == "ooh-platform"); (.status.phase == "Succeeded" or .status.phase == "Failed" or all(.spec.volumes[]?; has("persistentVolumeClaim") | not)))' >/dev/null <<< "$pods"; then break; fi
        (( SECONDS < deadline )) || stop 'pods still mount data disks; rerun install/85-aws-destroy.sh after investigating'
        sleep 10
    done
    for ns in ooh-apps ooh-platform; do
        kubectl -n "$ns" delete pvc --all --ignore-not-found --timeout=600s
        kubectl delete namespace "$ns" --ignore-not-found --wait=false
    done
    wait_no_data_volumes
}
destroy_exit() {
    local status=$?
    trap - EXIT ERR
    cleanup_plans || status=1
    if ! aws logout; then
        printf 'STOP: AWS logout failed; run aws logout before restarting a builder\n' >&2
        status=1
    fi
    (( status != 0 )) || printf 'DONE\n'
    exit "$status"
}
destroy_main() {
    local mode=${1:-} root state nodes addons=false cluster=false all=false
    [[ $# -le 1 && ( -z $mode || $mode == --all || $mode == --sweep-only ) ]] || stop 'use install/85-aws-destroy.sh [--all|--sweep-only]'
    AWS_PLANS=()
    if [[ $mode != --sweep-only ]]; then trap destroy_exit EXIT; fi
    aws_setup
    check_signin
    if [[ $mode == --sweep-only ]]; then sweep_empty; printf 'DONE\n'; return; fi
    check_age
    [[ $mode != --all ]] || all=true
    AWS_PLANS=("$AWS_CACHE/addons-destroy.tfplan" "$AWS_CACHE/cluster-destroy.tfplan" "$AWS_CACHE/bootstrap-destroy.tfplan")
    for root in addons cluster; do
        init_root "$root"
        state=$(terraform -chdir="$TF_ROOT/$root" state list)
        if [[ -n $state ]]; then
            if [[ $root == addons ]]; then addons=true; check_kube; else cluster=true; fi
            terraform -chdir="$TF_ROOT/$root" plan -destroy -input=false -out="$AWS_CACHE/$root-destroy.tfplan"
            show_plan "$root" "$AWS_CACHE/$root-destroy.tfplan"
        fi
    done
    printf '%s\n' 'Cleanup removes the controller-made NLB and data EBS disks before Terraform removes controllers, node, root disk, NAT and EKS; stops about USD 0.42/hour. All AWS copy test data is deleted.'
    # List controller-owned disks and front door so they are visible beside the plans.
    aws ec2 describe-volumes --filters Name=tag:ooh-stage,Values=4b --query 'Volumes[].{ID:VolumeId,GB:Size}' --output table
    cluster_load_balancers
    confirm 'Type yes to destroy the AWS copy'
    if $addons; then
        nodes=$(aws eks list-nodegroups --cluster-name ooh-aws --query nodegroups --output json)
        if jq -e 'index("main") != null' >/dev/null <<< "$nodes"; then clean_kubernetes; else printf 'INFO: no node group; Kubernetes data cleanup skipped\n'; fi
        apply_plan addons "$AWS_CACHE/addons-destroy.tfplan"
    fi
    if $cluster; then apply_plan cluster "$AWS_CACHE/cluster-destroy.tfplan"; fi
    sweep_empty
    if $all; then
        [[ -n ${BUDGET_EMAIL:-} ]] || stop 'budget email missing from private settings'
        export TF_VAR_budget_email="$BUDGET_EMAIL"
        init_root bootstrap
        terraform -chdir="$TF_ROOT/bootstrap" plan -destroy -input=false -out="$AWS_CACHE/bootstrap-destroy.tfplan"
        show_plan bootstrap "$AWS_CACHE/bootstrap-destroy.tfplan"
        printf 'Deletes every state bucket version and the budget; stops their small S3 charges.\n'
        confirm 'Type yes to destroy the state bucket, its history and the budget too'
        apply_plan bootstrap "$AWS_CACHE/bootstrap-destroy.tfplan"
        rm -f "$AWS_LOCAL/aws-backend.hcl"
    fi
    rm -f "$HOME/.kube/ooh-aws.config"
    local temp
    temp=$(mktemp "$AWS_LOCAL/aws.env.XXXXXX")
    awk '!/^(EKS_ENDPOINT|LB_HOSTNAME)=/' "$AWS_LOCAL/aws.env" > "$temp"
    mv "$temp" "$AWS_LOCAL/aws.env"
    printf '%s\n' 'Remove CNAME records: harness.aws.faysalaziz.com, admin.aws.faysalaziz.com, auth.aws.faysalaziz.com.'
    find "$AWS_CACHE" -maxdepth 1 -type f -name '*.tfplan' -delete
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then destroy_main "$@"; fi
