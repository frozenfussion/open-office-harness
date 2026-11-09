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
for setting in LETSENCRYPT_EMAIL SPACES_REGION SPACES_BUCKET; do
  [[ -n "${!setting:-}" ]] || stop "local setting $setting is empty; fill it in as described in README"
done
[[ "$LETSENCRYPT_EMAIL" == *@*.* && "$LETSENCRYPT_EMAIL" != *[[:space:]]* ]] || stop "contact email is invalid; correct local settings"
[[ "$SPACES_REGION" == sgp1 && "$SPACES_BUCKET" == ooh-files ]] || stop "Spaces settings must name sgp1 and ooh-files"

for tool in kubectl getent ss jq; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
kubectl get nodes -o json | jq -e '.items | length == 1 and all(.[]; any(.status.conditions[]; .type == "Ready" and .status == "True"))' >/dev/null || stop "k3s node is not Ready; check server setup"
printf 'PASS kubectl access and k3s node Ready\nPASS local settings complete\n'
for name in harness admin auth; do
  addresses="$(getent ahostsv4 "$name.$DOMAIN" | awk '{print $1}' | sort -u)" || stop "DNS lookup failed for $name.$DOMAIN; check its A record"
  [[ "$addresses" == "$PUBLIC_IP" ]] || stop "$name.$DOMAIN does not resolve only to $PUBLIC_IP; fix DNS or wait for it to spread"
  printf 'PASS DNS %s.%s\n' "$name" "$DOMAIN"
done
for port in 80 443; do
  listeners="$(ss -H -ltn "sport = :$port")"
  [[ -n "$listeners" ]] || stop "nothing listening on port $port; check k3s Traefik"
  printf 'PASS local listener port %s\n' "$port"
done
printf 'DONE\n'
