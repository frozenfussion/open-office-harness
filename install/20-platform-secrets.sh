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
command -v openssl >/dev/null || stop "missing tool openssl; finish server setup"
kubectl get namespace "$PLATFORM_NAMESPACE" >/dev/null 2>&1 || stop "platform namespace missing; run step 4 (operators) first"
existing="$(kubectl -n "$PLATFORM_NAMESPACE" get secrets -o json)"
has_secret() { jq -e --arg name "$1" 'any(.items[]; .metadata.name == $name)' <<< "$existing" >/dev/null; }
create_secret() {
  local name="$1" userkey="$2" passkey="$3" user="$4" password="$5" type="$6"
  # Feed generated secret values through stdin, never an external process argument.
  printf '%s\0' "$name" "$userkey" "$passkey" "$user" "$password" "$type" "$PLATFORM_NAMESPACE" |
    jq -Rs 'split("\u0000") as $v | {apiVersion:"v1",kind:"Secret",metadata:{name:$v[0],namespace:$v[6]},type:$v[5],stringData:{($v[1]):$v[3],($v[2]):$v[4]}}' |
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
