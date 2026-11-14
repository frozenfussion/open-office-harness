#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set -E
umask 077
export PATH="$HOME/.local/bin:$PATH" AWS_PAGER="" AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1
AWS_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
AWS_LOCAL="$HOME/.config/ooh"
AWS_CACHE="$HOME/.cache/ooh"
TF_ROOT="$AWS_ROOT/infra/terraform/aws"
export KUBECONFIG="$HOME/.kube/ooh-aws.config"
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
aws_setup() {
    install -d -m 700 "$AWS_LOCAL" "$AWS_CACHE"
    trap 'stop "AWS step failed; fix the error above and rerun this script; existing resources remain until install/85-aws-destroy.sh succeeds"' ERR
    # shellcheck source=/dev/null
    [[ -f $AWS_LOCAL/aws.env ]] && source "$AWS_LOCAL/aws.env"
    export AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1
    export EKS_CLUSTER_NAME=ooh-aws
}
save_setting() {
    local key=$1 value=$2 line temp
    [[ $key =~ ^[A-Z_]+$ && $value != *$'\n'* ]] || stop 'invalid local setting'
    temp=$(mktemp "$AWS_LOCAL/aws.env.XXXXXX")
    if [[ -f $AWS_LOCAL/aws.env ]]; then
        while IFS= read -r line; do [[ $line == "$key="* ]] || printf '%s\n' "$line"; done < "$AWS_LOCAL/aws.env" > "$temp"
    fi
    printf '%s=%q\n' "$key" "$value" >> "$temp"
    chmod 600 "$temp"
    mv "$temp" "$AWS_LOCAL/aws.env"
}
check_signin() {
    local caller expected bucket
    caller=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || stop 'AWS sign-in expired; run install/83-aws-login.sh'
    [[ $caller =~ ^[0-9]{12}$ ]] || stop 'AWS caller account is invalid'
    export AWS_ACCOUNT=$caller
    AWS_BUCKET="ooh-tfstate-${caller}-apse1"
    if [[ -f $AWS_LOCAL/aws-backend.hcl ]]; then
        bucket=$(awk -F '"' '/^bucket *=/ {print $2}' "$AWS_LOCAL/aws-backend.hcl")
        expected="ooh-tfstate-${caller}-apse1"
        [[ $bucket == "$expected" ]] || stop 'caller account differs from the state bucket account; nothing was changed'
    fi
    export TF_VAR_state_bucket="$AWS_BUCKET"
}
check_age() {
    local signed now
    [[ -n ${AWS_SIGNIN_AT:-} ]] || stop 'AWS sign-in time missing; run install/83-aws-login.sh'
    signed=$(date -u -d "$AWS_SIGNIN_AT" +%s) || stop 'invalid AWS sign-in time; run install/83-aws-login.sh'
    now=$(date -u +%s)
    (( now >= signed && now - signed < 39600 )) || stop 'AWS sign-in older than 11 hours; run install/83-aws-login.sh'
}
check_kube() {
    local server
    [[ -n ${EKS_ENDPOINT:-} && -f $KUBECONFIG ]] || stop 'AWS kubeconfig or endpoint missing; rerun install/82-aws-cluster.sh'
    server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
    [[ $server == "$EKS_ENDPOINT" ]] || stop "this shell points at $server, not the AWS cluster; nothing was changed"
    # Freeze the dedicated kubeconfig before any call that reaches Kubernetes.
    local frozen
    frozen=$(mktemp "$AWS_CACHE/kube.XXXXXX")
    kubectl config view --minify --flatten > "$frozen"
    chmod 600 "$frozen"
    export KUBECONFIG="$frozen"
    AWS_FROZEN=$frozen
}
cleanup_plans() {
    local plan
    for plan in "${AWS_PLANS[@]}"; do rm -f "$plan"; done
    [[ -z ${AWS_FROZEN:-} ]] || rm -f "$AWS_FROZEN"
}
init_root() {
    local root=$1
    if [[ $root == bootstrap ]]; then
        install -d -m 700 "$AWS_LOCAL/terraform"
        terraform -chdir="$TF_ROOT/$root" init -input=false -reconfigure -backend-config="path=$AWS_LOCAL/terraform/bootstrap.tfstate"
    else
        [[ -f $AWS_LOCAL/aws-backend.hcl ]] || stop 'state bucket settings missing; run install/81-aws-bootstrap.sh'
        terraform -chdir="$TF_ROOT/$root" init -input=false -reconfigure -backend-config="$AWS_LOCAL/aws-backend.hcl" -backend-config="key=$root/terraform.tfstate"
    fi
}
show_plan() { terraform -chdir="$TF_ROOT/$1" show -no-color "$2"; }
confirm() {
    local answer
    read -r -p "$1: " answer || stop 'confirmation was not supplied'
    [[ $answer == yes ]] || stop 'not confirmed; saved plans removed; nothing else was changed'
}
apply_plan() {
    check_signin
    terraform -chdir="$TF_ROOT/$1" apply -input=false "$2"
    rm -f "$2"
}
price_table() {
    printf '%s\n' 'Singapore prices checked 2026-11-14 (USD/hour):' \
      'EKS 0.10; t3.xlarge 0.2112; NAT 0.059 (+0.059/GB); NLB 0.0252 (+~0.006/capacity unit).' \
      'EBS gp3 110 GB ~0.015; two public IPv4 addresses 0.010.' \
      'Total about USD 0.42/hour, USD 10.10/day; images ~USD 0.30 per pull; internet traffic USD 0.12/GB.'
}
bootstrap_main() {
    aws_setup
    check_signin
    check_age
    AWS_PLANS=("$AWS_CACHE/bootstrap.tfplan")
    trap cleanup_plans EXIT
    if [[ -z ${BUDGET_EMAIL:-} ]]; then read -r -p 'Budget email address (kept only in private local settings): ' BUDGET_EMAIL; fi
    [[ $BUDGET_EMAIL =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || stop 'enter a valid budget email address'
    save_setting BUDGET_EMAIL "$BUDGET_EMAIL"
    save_setting AWS_REGION ap-southeast-1
    save_setting EKS_CLUSTER_NAME ooh-aws
    export TF_VAR_budget_email="$BUDGET_EMAIL"
    init_root bootstrap
    terraform -chdir="$TF_ROOT/bootstrap" plan -input=false -out="${AWS_PLANS[0]}"
    show_plan bootstrap "${AWS_PLANS[0]}"
    printf '%s\n' 'Creates a versioned, private encrypted state bucket and USD 40 monthly budget; about USD 0/hour (small S3 storage/request charges).'
    confirm 'Type yes to build state bucket and budget (about USD 0/hour)'
    apply_plan bootstrap "${AWS_PLANS[0]}"
    printf 'bucket = "%s"\nkey = "cluster/terraform.tfstate"\nregion = "ap-southeast-1"\nuse_lockfile = true\n' "$AWS_BUCKET" > "$AWS_LOCAL/aws-backend.hcl"
    chmod 600 "$AWS_LOCAL/aws-backend.hcl"
    install -d -m 700 "$AWS_LOCAL/aws"
    if [[ ! -f $AWS_LOCAL/aws/do.env ]]; then
        [[ -f $AWS_LOCAL/do.env ]] || stop 'Droplet certificate email settings missing; finish the existing platform setup first'
        local LETSENCRYPT_EMAIL
        # shellcheck source=/dev/null
        source "$AWS_LOCAL/do.env"
        [[ -n ${LETSENCRYPT_EMAIL:-} ]] || stop 'Droplet certificate email is missing'
        printf 'LETSENCRYPT_EMAIL=%q\n' "$LETSENCRYPT_EMAIL" > "$AWS_LOCAL/aws/do.env"
        chmod 600 "$AWS_LOCAL/aws/do.env"
    fi
    printf 'DONE\n'
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
