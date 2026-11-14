#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "admin request failed; check Keycloak and re-run; existing users are never overwritten"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
command -v curl >/dev/null || stop "missing tool curl; finish server setup"
command -v jq >/dev/null || stop "missing tool jq; finish server setup"
base="https://auth.$DOMAIN"
read -r -p 'First admin username: ' username
read -r -p 'First admin email: ' email
read -r -s -p 'First admin password (hidden): ' password; printf '\n'
read -r -s -p 'Repeat password (hidden): ' confirmation; printf '\n'
[[ -n "$username" && "$email" == *@*.* && -n "$password" && "$password" == "$confirmation" ]] || stop "username/email/password missing or passwords differ; re-run"
bootstrap="$(kubectl -n "$PLATFORM_NAMESPACE" get secret keycloak-bootstrap -o json)"
bootstrap_user="$(jq -r '.data.username | @base64d' <<< "$bootstrap")"
bootstrap_password="$(jq -r '.data.password | @base64d' <<< "$bootstrap")"
request() {
  local reply status body reason secret encoded
  reply="$(curl --connect-timeout 10 --max-time 30 -sS -w '\n%{http_code}' "$@" 2>/dev/null)" ||
    stop "Keycloak request could not reach the server; check readiness and retry"
  status="${reply##*$'\n'}"
  body="${reply%$'\n'*}"
  if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then printf '%s' "$body"; return 0; fi
  reason="$(jq -r '[.errorMessage, .error_description] | map(select(type == "string" and length > 0)) | .[0] // empty' <<< "$body" 2>/dev/null)" || reason=''
  for secret in "${password:-}" "${confirmation:-}" "${bootstrap_password:-}" "${token:-}"; do
    [[ -n "$secret" ]] || continue
    reason="${reason//"$secret"/[REDACTED]}"
    encoded="$(printf '%s' "$secret" | jq -sRr @uri)"
    reason="${reason//"$encoded"/[REDACTED]}"
    encoded="$(printf '%s' "$secret" | jq -sR .)"
    encoded="${encoded:1:${#encoded}-2}"
    reason="${reason//"$encoded"/[REDACTED]}"
  done
  reason="$(printf '%s' "$reason" | jq -sRr 'gsub("[\u0000-\u001f\u007f]"; " ")')"
  [[ -n "$reason" ]] || reason='no error reason supplied'
  stop "Keycloak refused request (HTTP $status): $reason"
}
# Generated bootstrap values are URL-safe. Send them through stdin, never command arguments.
token="$(printf 'client_id=admin-cli&grant_type=password&username=%s&password=%s' "$bootstrap_user" "$bootstrap_password" |
  request --data-binary @- "$base/realms/master/protocol/openid-connect/token" | jq -er '.access_token')" || exit 1
unset bootstrap bootstrap_user bootstrap_password
api() {
  printf 'header = "Authorization: Bearer %s"\n' "$token" |
    request --config - "$@"
}
# Refuse to create another first admin once a permanent administrator exists.
admins="$(api "$base/admin/realms/ooh/roles/ooh-admin/users?max=-1")" || exit 1
[[ "$(jq '[.[] | select(.serviceAccountClientId == null and ((.username // "") | startswith("service-account-") | not))] | length' <<< "$admins")" == 0 ]] || { printf 'First admin already exists; no changes made\nDONE\n'; exit 0; }
existing="$(api --get --data-urlencode username@/dev/fd/4 --data-urlencode exact=true "$base/admin/realms/ooh/users" 4< <(printf '%s' "$username"))" || exit 1
count="$(jq 'length' <<< "$existing")"
if [[ "$count" != 0 ]]; then
  jq -e 'length == 1 and .[0].attributes["ooh-first-admin"] == ["true"]' <<< "$existing" >/dev/null || stop "username already exists; inspect the account before retrying; it will not be overwritten"
  printf 'Completing role assignment for the first admin created by this script; password unchanged\n'
else
# Curl's config holds only the token; the JSON body arrives on a separate descriptor.
payload="$(printf '%s\0%s\0%s' "$username" "$email" "$password" |
  jq -Rs 'split("\u0000") as $v | {username:$v[0],email:$v[1],enabled:true,attributes:{"ooh-first-admin":["true"]},requiredActions:[],credentials:[{type:"password",value:$v[2],temporary:false}]}')"
request --config /dev/fd/3 -X POST -H 'Content-Type: application/json' --data-binary @- "$base/admin/realms/ooh/users" 3< <(printf 'header = "Authorization: Bearer %s"\n' "$token") <<< "$payload" >/dev/null || exit 1
fi
unset password confirmation payload
users="$(api --get --data-urlencode username@/dev/fd/4 --data-urlencode exact=true "$base/admin/realms/ooh/users" 4< <(printf '%s' "$username"))" || exit 1
id="$(jq -er 'if length == 1 then .[0].id else error("user lookup failed") end' <<< "$users")"
role="$(api "$base/admin/realms/ooh/roles/ooh-admin" | jq -c '[{id:.id,name:.name}]')" || exit 1
request --config /dev/fd/3 -X POST -H 'Content-Type: application/json' --data-binary @- "$base/admin/realms/ooh/users/$id/role-mappings/realm" 3< <(printf 'header = "Authorization: Bearer %s"\n' "$token") <<< "$role" >/dev/null || exit 1
unset token users username email id role
printf 'First admin created with ooh-admin; sign in at %s/realms/ooh/account\nDONE\n' "$base"
