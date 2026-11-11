#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Slides worker setup failed; inspect platform readiness and re-run install/72-slides-worker-setup.sh"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE; do
  [[ -n "${!variable:-}" && "${!variable}" != *[!a-zA-Z0-9.-]* ]] || stop "invalid deployment value $variable; correct deploy/values/do.env"
done
render() {
  local source="$1" target="$2" line variable token
  while IFS= read -r line || [[ -n "$line" ]]; do
    for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE; do
      token="\${$variable}"
      line="${line//"$token"/"${!variable}"}"
    done
    printf '%s\n' "$line"
  done < "$source" > "$target"
}
[[ $# == 0 ]] || stop "usage: install/72-slides-worker-setup.sh"
for tool in kubectl jq base64 mktemp; do
  command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"
done
name=slides-worker
 deadline=$((SECONDS + 120))
 while :; do
   ready="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkauser "$name" --ignore-not-found -o json 2>/dev/null)" || ready=''
   current="$(kubectl -n "$PLATFORM_NAMESPACE" get secret "$name" --ignore-not-found -o jsonpath='{.data.password}' 2>/dev/null)" || current=''
   if [[ -n "$ready" && -n "$current" ]] && jq -e 'any(.status.conditions[]?; .type == "Ready" and .status == "True")' <<< "$ready" >/dev/null; then break; fi
   ((SECONDS < deadline)) || stop "KafkaUser $name not ready; re-run 30"
   sleep 2
 done
 existing="$(kubectl -n "$APPS_NAMESPACE" get secret "$name-kafka" --ignore-not-found -o json)"
 if [[ -n "$existing" ]]; then
   stored="$(jq -er '.data.password' <<< "$existing")"
   [[ "$stored" == "$current" ]] || stop "Kafka password changed in Strimzi; ask the maintainer before replacing $name-kafka"
 else
   printf '%s' "$current" | jq -Rs --arg namespace "$APPS_NAMESPACE" --arg name "$name-kafka" '{apiVersion:"v1",kind:"Secret",metadata:{name:$name,namespace:$namespace},type:"Opaque",data:{password:.}}' | kubectl create -f - >/dev/null
 fi
 unset ready current stored existing
# Authentication and CLI settings remain inside the Keycloak pod.
# shellcheck disable=SC2016
client_secret="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- /bin/bash -c '
  set -euo pipefail
  set +x
  umask 077
  config_dir=$(mktemp -d /tmp/ooh-slides-setup.XXXXXXXX)
  trap '"'"'rm -rf -- "$config_dir"'"'"' EXIT
  config="$config_dir/kcadm.config"
  /opt/keycloak/bin/kcadm.sh config credentials --config "$config" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  clients=$(/opt/keycloak/bin/kcadm.sh get clients -r ooh -q clientId=ooh-slides-worker --fields id,clientId --config "$config" 2>/dev/null)
  id=$(printf "%s" "$clients" | sed -n '"'"'s/.*"id"[[:space:]]*:[[:space:]]*"\([a-zA-Z0-9-]*\)".*/\1/p'"'"')
  [[ "$id" =~ ^[a-zA-Z0-9-]+$ ]]
  /opt/keycloak/bin/kcadm.sh get "clients/$id/client-secret" -r ooh --config "$config" 2>/dev/null
' 2>/dev/null | jq -ej '.value | select(type == "string" and length > 0)')" || stop "could not read Slides worker client secret; inspect Keycloak readiness and bootstrap access"
existing="$(kubectl -n "$APPS_NAMESPACE" get secret slides-worker-oidc --ignore-not-found -o json)"
if [[ -n "$existing" ]]; then
  stored="$(jq -er '.data["client-secret"]' <<< "$existing" | base64 --decode)"
  [[ "$stored" == "$client_secret" ]] || stop "Slides worker client secret changed; ask the maintainer before replacing slides-worker-oidc"
else
  printf '%s' "$client_secret" |
    jq -Rs --arg namespace "$APPS_NAMESPACE" '{apiVersion:"v1",kind:"Secret",metadata:{name:"slides-worker-oidc",namespace:$namespace},type:"Opaque",stringData:{"client-secret":.}}' |
    kubectl create -f - >/dev/null
fi
unset client_secret stored existing
printf 'DONE\n'
