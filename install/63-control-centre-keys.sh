#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "encryption Secret setup failed; check cluster access and retry"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
[[ $# == 0 ]] || stop "usage: install/63-control-centre-keys.sh"
for tool in kubectl openssl jq; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
[[ "$APPS_NAMESPACE" =~ ^[a-z0-9-]+$ ]] || stop "invalid application namespace; correct deploy/values/do.env"
if kubectl -n "$APPS_NAMESPACE" get secret control-centre-keys >/dev/null 2>&1; then
  printf 'Existing encryption Secret retained; it will never be overwritten\nDONE\n'
  exit 0
fi
key="$(openssl rand -base64 32)"
printf '%s' "$key" | jq -Rs --arg ns "$APPS_NAMESPACE" '{apiVersion:"v1",kind:"Secret",metadata:{name:"control-centre-keys",namespace:$ns},type:"Opaque",stringData:{"encryption-key":.}}' | kubectl create -f - >/dev/null
unset key
printf 'DONE\n'
