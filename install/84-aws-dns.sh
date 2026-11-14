#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
# shellcheck source=install/81-aws-bootstrap.sh
source "$(dirname "${BASH_SOURCE[0]}")/81-aws-bootstrap.sh"
check_dns() {
    local name found response
    [[ -n ${LB_HOSTNAME:-} ]] || stop 'load balancer hostname missing; run install/82-aws-cluster.sh'
    for name in harness admin auth; do
        found=$(dig +short CNAME "$name.aws.faysalaziz.com")
        [[ ${found%.} == "$LB_HOSTNAME" ]] || stop "$name.aws.faysalaziz.com CNAME does not point at the AWS load balancer; check DNS and retry"
        response=$(curl --silent --show-error --max-time 30 -D - -o /dev/null "http://$name.aws.faysalaziz.com/")
        [[ $response == HTTP/* ]] || stop "$name.aws.faysalaziz.com port 80 did not reach Traefik"
        printf 'PASS: %s CNAME and HTTP port 80\n' "$name.aws.faysalaziz.com"
    done
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    aws_setup
    check_signin
    check_dns
    printf 'DONE\n'
fi
