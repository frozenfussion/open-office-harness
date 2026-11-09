#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "step failed; see README troubleshooting and re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
command -v openssl >/dev/null || stop "missing tool openssl; finish server setup"
kubectl get namespace ooh-platform >/dev/null
existing="$(kubectl -n ooh-platform get secrets -o json)"
has_secret() { jq -e --arg name "$1" 'any(.items[]; .metadata.name == $name)' <<< "$existing" >/dev/null; }
create_secret() {
  local name="$1" userkey="$2" passkey="$3" user="$4" password="$5" type="$6"
  jq -n --arg name "$name" --arg uk "$userkey" --arg pk "$passkey" --arg u "$user" --arg p "$password" --arg type "$type" \
    '{apiVersion:"v1",kind:"Secret",metadata:{name:$name,namespace:"ooh-platform"},type:$type,stringData:{($uk):$u,($pk):$p}}' |
    kubectl create -f - >/dev/null
  printf 'Created %s\n' "$name"
}
for name in keycloak-db keycloak-bootstrap; do
  if has_secret "$name"; then printf 'Already exists: %s\n' "$name"; continue; fi
  case "$name" in
    keycloak-db) create_secret "$name" username password keycloak "$(openssl rand -hex 32)" kubernetes.io/basic-auth ;;
    keycloak-bootstrap) create_secret "$name" username password bootstrap-admin "$(openssl rand -hex 32)" kubernetes.io/basic-auth ;;
  esac
done
unset existing
printf 'DONE\n'
