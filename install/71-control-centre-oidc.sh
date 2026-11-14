#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# shellcheck disable=SC2016 # These variables expand only inside Keycloak.
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Control Centre service credential setup failed; check cluster access and retry"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
[[ $# == 0 ]] || stop "usage: install/71-control-centre-oidc.sh"
for tool in kubectl jq base64; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
for variable in PLATFORM_NAMESPACE APPS_NAMESPACE; do
  [[ "${!variable:-}" =~ ^[a-z0-9-]+$ ]] || stop "invalid namespace; correct deploy/values/$OOH_TARGET.env"
done
client_secret="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- bash -c '
  set -euo pipefail
  set +x
  umask 077
  private_dir=$(mktemp -d /tmp/ooh-centre-oidc.XXXXXXXX)
  trap '\''rm -rf -- "$private_dir"'\'' EXIT
  cli=/opt/keycloak/bin/kcadm.sh
  "$cli" config credentials --config "$private_dir/config" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  clients=$("$cli" get clients -r ooh -q clientId=ooh-control-centre --fields id,clientId --config "$private_dir/config" 2>/dev/null)
  id=$(printf "%s" "$clients" | sed -n '\''s/.*"id" *: *"\([^" ]*\)".*/\1/p'\'')
  [[ "$id" =~ ^[a-f0-9-]{36}$ ]]
  "$cli" get "clients/$id/client-secret" -r ooh --config "$private_dir/config" 2>/dev/null
')" || stop "could not read Control Centre client secret; check Keycloak bootstrap access privately"
client_secret="$(printf '%s' "$client_secret" | jq -ej '.value | select(type == "string" and length > 0)')" || stop "Control Centre client secret missing; inspect the realm client privately"
existing="$(kubectl -n "$APPS_NAMESPACE" get secret control-centre-oidc --ignore-not-found -o json)"
if [[ -n "$existing" ]]; then
  stored="$(printf '%s' "$existing" | jq -r '.data["client-secret"] // ""')"
  current="$(printf '%s' "$client_secret" | base64 -w0)"
  [[ "$stored" == "$current" ]] || stop "the Control Centre client secret changed; ask the maintainer before replacing control-centre-oidc"
else
  printf '%s' "$client_secret" | jq -Rs --arg namespace "$APPS_NAMESPACE" '{apiVersion:"v1",kind:"Secret",metadata:{name:"control-centre-oidc",namespace:$namespace},type:"Opaque",stringData:{"client-secret":.}}' | kubectl create -f - >/dev/null
fi
unset client_secret stored current existing
printf 'DONE\n'
