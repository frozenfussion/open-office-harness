#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "step failed; see README troubleshooting and re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
[[ -f "$HOME/.config/ooh/do.env" ]] || stop "local settings missing; copy install/ooh.env.example as described in README"
# shellcheck source=/dev/null
source "$HOME/.config/ooh/do.env"
[[ -n "${LETSENCRYPT_EMAIL:-}" ]] || stop "local setting LETSENCRYPT_EMAIL is empty; fill it in as described in README"
[[ "$LETSENCRYPT_EMAIL" == *@*.* && "$LETSENCRYPT_EMAIL" != *[[:space:]]* ]] || stop "contact email is invalid; correct local settings"

for tool in kubectl getent curl jq; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
kubectl get nodes -o json | jq -e '.items | length == 1 and all(.[]; any(.status.conditions[]; .type == "Ready" and .status == "True"))' >/dev/null || stop "k3s node is not Ready; check server setup"
printf 'PASS kubectl access and k3s node Ready\nPASS local settings complete\n'
for name in harness admin auth; do
  addresses="$(getent ahostsv4 "$name.$DOMAIN" | awk '{print $1}' | sort -u)" || stop "DNS lookup failed for $name.$DOMAIN; check its A record"
  [[ "$addresses" == "$PUBLIC_IP" ]] || stop "$name.$DOMAIN does not resolve only to $PUBLIC_IP; fix DNS or wait for it to spread"
  printf 'PASS DNS %s.%s\n' "$name" "$DOMAIN"
done
kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik -o json |
  jq -e '.items | length > 0 and all(.[]; any(.status.conditions[]?; .type == "Ready" and .status == "True"))' >/dev/null || stop "Traefik pod is missing or not Ready in kube-system; check k3s Traefik"
printf 'PASS Traefik pod Ready in kube-system\n'
# ServiceLB forwards ports without a process listening in ss. Any HTTP response proves local routing.
for url in http://127.0.0.1/ https://127.0.0.1/; do
  options=()
  # The default local certificate is not trusted before platform TLS is installed.
  [[ "$url" != https:* ]] || options+=(--insecure)
  status="$(curl "${options[@]}" --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}' "$url")" || stop "local Traefik request failed for $url; check Traefik and ServiceLB"
  [[ "$status" =~ ^[1-5][0-9][0-9]$ ]] || stop "no HTTP status from $url; check Traefik and ServiceLB"
  printf 'PASS local Traefik %s returned HTTP %s\n' "$url" "$status"
done
printf 'DONE\n'
