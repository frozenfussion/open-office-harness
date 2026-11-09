#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "admin request failed; check Keycloak and re-run; existing users are never overwritten"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
command -v curl >/dev/null || stop "missing tool curl; finish server setup"
command -v jq >/dev/null || stop "missing tool jq; finish server setup"
base="https://auth.$DOMAIN"
bootstrap="$(kubectl -n "$PLATFORM_NAMESPACE" get secret keycloak-bootstrap -o json)"
bootstrap_user="$(jq -r '.data.username | @base64d' <<< "$bootstrap")"
bootstrap_password="$(jq -r '.data.password | @base64d' <<< "$bootstrap")"
# Generated bootstrap values are URL-safe. Send them through stdin, never command arguments.
token="$(printf 'client_id=admin-cli&grant_type=password&username=%s&password=%s' "$bootstrap_user" "$bootstrap_password" |
  curl --connect-timeout 10 --max-time 30 -fsS --data-binary @- "$base/realms/master/protocol/openid-connect/token" 2>/dev/null | jq -er '.access_token')"
unset bootstrap bootstrap_user bootstrap_password
api() {
  printf 'header = "Authorization: Bearer %s"\n' "$token" |
    curl --config - --connect-timeout 10 --max-time 30 -fsS "$@" 2>/dev/null
}
# Refuse to create another first admin once a permanent administrator exists.
admins="$(api "$base/admin/realms/ooh/roles/ooh-admin/users?max=1")"
[[ "$(jq 'length' <<< "$admins")" == 0 ]] || { printf 'First admin already exists; no changes made\nDONE\n'; exit 0; }
read -r -p 'First admin username: ' username
read -r -p 'First admin email: ' email
read -r -s -p 'First admin password (hidden): ' password; printf '\n'
read -r -s -p 'Repeat password (hidden): ' confirmation; printf '\n'
[[ -n "$username" && "$email" == *@*.* && -n "$password" && "$password" == "$confirmation" ]] || stop "username/email/password missing or passwords differ; re-run"
existing="$(api --get --data-urlencode "username=$username" --data-urlencode exact=true "$base/admin/realms/ooh/users")"
count="$(jq 'length' <<< "$existing")"
if [[ "$count" != 0 ]]; then
  jq -e 'length == 1 and .[0].attributes["ooh-first-admin"] == ["true"]' <<< "$existing" >/dev/null || stop "username already exists; inspect the account before retrying; it will not be overwritten"
  printf 'Completing role assignment for the first admin created by this script; password unchanged\n'
else
# Curl's config holds only the token; the JSON body arrives on a separate descriptor.
payload="$(jq -n --arg u "$username" --arg e "$email" --arg p "$password" '{username:$u,email:$e,enabled:true,attributes:{"ooh-first-admin":["true"]},requiredActions:["UPDATE_PASSWORD"],credentials:[{type:"password",value:$p,temporary:true}]}')"
curl --config /dev/fd/3 --connect-timeout 10 --max-time 30 -fsS -X POST -H 'Content-Type: application/json' --data-binary @- "$base/admin/realms/ooh/users" 3< <(printf 'header = "Authorization: Bearer %s"\n' "$token") <<< "$payload" >/dev/null 2>&1
fi
unset password confirmation payload
users="$(api --get --data-urlencode "username=$username" --data-urlencode exact=true "$base/admin/realms/ooh/users")"
id="$(jq -er 'if length == 1 then .[0].id else error("user lookup failed") end' <<< "$users")"
role="$(api "$base/admin/realms/ooh/roles/ooh-admin" | jq -c '[{id:.id,name:.name}]')"
curl --config /dev/fd/3 --connect-timeout 10 --max-time 30 -fsS -X POST -H 'Content-Type: application/json' --data-binary @- "$base/admin/realms/ooh/users/$id/role-mappings/realm" 3< <(printf 'header = "Authorization: Bearer %s"\n' "$token") <<< "$role" >/dev/null 2>&1
unset token users username email id role
printf 'First admin created with ooh-admin; sign in at %s/realms/ooh/account and change the password\nDONE\n' "$base"
