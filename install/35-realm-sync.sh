#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "realm audience sync failed; inspect Keycloak readiness and bootstrap access, then re-run step 6"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
for tool in kubectl jq awk; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
# Read only the client IDs and included audiences from the controlled realm YAML format.
awk '/(^|[[:space:]])[&*][a-zA-Z0-9]/ {exit 1}' deploy/platform/keycloak/realm-ooh.yaml || stop "realm client format changed; expand YAML aliases before syncing"
rows="$(awk '
  $1 == "-" && $2 == "clientId:" {client=$3; print "CLIENT\t" client}
  $1 == "included.client.audience:" {print "AUDIENCE\t" client "\t" $2}
' deploy/platform/keycloak/realm-ooh.yaml)"
desired="$(jq -Rn '[inputs | split("\t")] | reduce .[] as $row ({}; if $row[0] == "CLIENT" then .[$row[1]] = [] else .[$row[1]] += [$row[2]] end)' <<< "$rows")"
jq -e 'keys | sort == (["ooh-workspace","ooh-admin-console","ooh-harness-api","ooh-control-centre","ooh-model-gateway"] | sort)' <<< "$desired" >/dev/null || stop "realm client format changed; check realm-ooh.yaml before syncing"
config_dir=''
cleanup() {
  if [[ "$config_dir" =~ ^/tmp/ooh-realm-sync\.[a-zA-Z0-9]+$ ]]; then
    kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- rm -rf -- "$config_dir" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
config_dir="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- /bin/bash -c 'umask 077; mktemp -d /tmp/ooh-realm-sync.XXXXXXXX')"
[[ "$config_dir" =~ ^/tmp/ooh-realm-sync\.[a-zA-Z0-9]+$ ]] || stop "could not create private Keycloak CLI settings directory"
config="$config_dir/kcadm.config"
bootstrap="$(kubectl -n "$PLATFORM_NAMESPACE" get secret keycloak-bootstrap -o json)"
username="$(jq -er '.data.username | @base64d' <<< "$bootstrap")"
password="$(jq -er '.data.password | @base64d' <<< "$bootstrap")"
# Credentials enter the pod over stdin and are never written to repository files or logs.
# shellcheck disable=SC2016 # Expanded by bash inside the Keycloak pod.
printf '%s\n%s\n' "$username" "$password" |
  kubectl -n "$PLATFORM_NAMESPACE" exec -i ooh-keycloak-0 -c keycloak -- /bin/bash -c '
    set -euo pipefail
    set +x
    umask 077
    read -r username
    read -r password
    /opt/keycloak/bin/kcadm.sh config credentials --config "$1" --server http://localhost:8080 --realm master --user "$username" --password "$password" >/dev/null 2>&1
  ' -- "$config"
unset bootstrap username password
kcadm() {
  local options=()
  [[ "$1" != update ]] || options+=(-i)
  kubectl -n "$PLATFORM_NAMESPACE" exec "${options[@]}" ooh-keycloak-0 -c keycloak -- /opt/keycloak/bin/kcadm.sh "$@" --config "$config" 2>/dev/null
}
while IFS= read -r client; do
  representation="$(kcadm get clients -r ooh -q "clientId=$client" --fields id,clientId,protocolMappers)"
  id="$(jq -er --arg client "$client" 'if length == 1 and .[0].clientId == $client then .[0].id else error("client missing or ambiguous") end' <<< "$representation")"
  audiences="$(jq -c --arg client "$client" '.[$client]' <<< "$desired")"
  # Keep other mapper types; only the client audience mappers are synchronized.
  update="$(jq -c --argjson audiences "$audiences" '{protocolMappers: ((.[0].protocolMappers // [] | map(select(.protocolMapper != "oidc-audience-mapper"))) + ($audiences | map({name:("audience-" + .),protocol:"openid-connect",protocolMapper:"oidc-audience-mapper",consentRequired:false,config:{"included.client.audience":.,"access.token.claim":"true","id.token.claim":"false"}})))}' <<< "$representation")"
  printf '%s\n' "$update" | kcadm update "clients/$id" -r ooh -f - >/dev/null
  actual="$(kcadm get "clients/$id" -r ooh --fields protocolMappers)"
  jq -e --argjson expected "$audiences" '[.protocolMappers[]? | select(.protocolMapper == "oidc-audience-mapper")] | all(.[]; .config["access.token.claim"] == "true" and .config["id.token.claim"] == "false") and (map(.config["included.client.audience"]) | sort == ($expected | sort))' <<< "$actual" >/dev/null || stop "audience verification failed for $client; re-run step 6"
  printf 'Synced audience mappers: %s\n' "$client"
done < <(jq -r 'keys[]' <<< "$desired")
printf 'DONE\n'
