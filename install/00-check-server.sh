#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "step failed; see README troubleshooting and re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
[[ -f "$OOH_LOCAL/do.env" ]] || stop "local settings missing; copy install/ooh.env.example as described in README"
# shellcheck source=/dev/null
source "$OOH_LOCAL/do.env"
[[ -n "${LETSENCRYPT_EMAIL:-}" ]] || stop "local setting LETSENCRYPT_EMAIL is empty; fill it in as described in README"
[[ "$LETSENCRYPT_EMAIL" == *@*.* && "$LETSENCRYPT_EMAIL" != *[[:space:]]* ]] || stop "contact email is invalid; correct local settings"

for tool in kubectl getent curl jq; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
kubectl get nodes -o json | jq -e --argjson expected "$EXPECTED_NODES" '.items | length == $expected and all(.[]; any(.status.conditions[]; .type == "Ready" and .status == "True"))' >/dev/null || stop "$OOH_TARGET nodes are not Ready; check server setup"
printf 'PASS kubectl access and %s Ready node(s) on %s\nPASS local settings complete\n' "$EXPECTED_NODES" "$OOH_TARGET"
if [[ "$OOH_TARGET" == aws ]]; then
  command -v dig >/dev/null || stop 'missing tool dig; finish server setup'
  [[ -n "$LB_HOSTNAME" ]] || stop 'AWS load balancer name missing; run install/82-aws-cluster.sh'
fi
for name in harness admin auth; do
  if [[ "$OOH_TARGET" == aws ]]; then
    cname="$(dig +short CNAME "$name.$DOMAIN")" || stop "DNS lookup failed for $name.$DOMAIN; check its CNAME record"
    [[ "${cname%.}" == "${LB_HOSTNAME%.}" ]] || stop "$name.$DOMAIN is not a CNAME to $LB_HOSTNAME; fix DNS or wait for it to spread"
  else
    addresses="$(getent ahostsv4 "$name.$DOMAIN" | awk '{print $1}' | sort -u)" || stop "DNS lookup failed for $name.$DOMAIN; check its A record"
    [[ "$addresses" == "$PUBLIC_IP" ]] || stop "$name.$DOMAIN does not resolve only to $PUBLIC_IP; fix DNS or wait for it to spread"
  fi
  printf 'PASS DNS %s.%s\n' "$name" "$DOMAIN"
done
kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik -o json |
  jq -e '.items | length > 0 and all(.[]; any(.status.conditions[]?; .type == "Ready" and .status == "True"))' >/dev/null || stop "Traefik pod is missing or not Ready in kube-system; check $OOH_TARGET Traefik"
printf 'PASS Traefik pod Ready in kube-system\n'
# ServiceLB forwards ports without a process listening in ss. Any HTTP response proves local routing.
front_door=127.0.0.1
[[ "$OOH_TARGET" != aws ]] || front_door=$LB_HOSTNAME
for url in "http://$front_door/" "https://$front_door/"; do
  options=()
  # The default local certificate is not trusted before platform TLS is installed.
  [[ "$url" != https:* ]] || options+=(--insecure)
  status="$(curl "${options[@]}" --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}' "$url")" || stop "target Traefik request failed for $url; check the $OOH_TARGET front door"
  [[ "$status" =~ ^[1-5][0-9][0-9]$ ]] || stop "no HTTP status from $url; check the $OOH_TARGET front door"
  printf 'PASS target Traefik %s returned HTTP %s\n' "$url" "$status"
done
printf 'DONE\n'
