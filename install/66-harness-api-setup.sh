#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "database setup failed; inspect PostgreSQL readiness and re-run install/66-harness-api-setup.sh"' ERR
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
[[ $# == 0 ]] || stop "usage: install/66-harness-api-setup.sh"
for tool in kubectl jq openssl base64 mktemp; do
  command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"
done
kubectl get namespace "$PLATFORM_NAMESPACE" >/dev/null 2>&1 || stop "platform namespace missing; run install/30-platform-apply.sh first"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready cluster.postgresql.cnpg.io/ooh-pg --timeout=300s ||
  stop "PostgreSQL is not Ready; check the platform before retrying"

for name in harness harness-app harness-test harness-test-app; do
  role="${name//-/_}"
  existing="$(kubectl -n "$PLATFORM_NAMESPACE" get secret "$name-db" --ignore-not-found -o json)"
  if [[ -n "$existing" ]]; then
    # Reject malformed existing secrets without ever displaying their contents.
    if ! printf '%s' "$existing" | jq -e --arg role "$role" '
      .type == "kubernetes.io/basic-auth" and
      ((.data.username // "" | @base64d) == $role) and
      ((.data.password // "" | @base64d) | test("^[a-f0-9]{64}$"))
    ' >/dev/null 2>&1; then
      stop "existing $name-db secret has unexpected credentials; ask the maintainer to inspect it privately"
    fi
    printf 'Already exists: %s-db\n' "$name"
  else
    password="$(openssl rand -hex 32)"
    printf '%s\0' "$name-db" "$role" "$password" |
      jq -Rs --arg namespace "$PLATFORM_NAMESPACE" 'split("\u0000") as $v | {apiVersion:"v1",kind:"Secret",metadata:{name:$v[0],namespace:$namespace},type:"kubernetes.io/basic-auth",stringData:{username:$v[1],password:$v[2]}}' |
      kubectl create -f - >/dev/null
    unset password
    printf 'Created %s-db\n' "$name"
  fi
  unset existing
done

manifest_tmp="$(mktemp)"
settings_tmp=''
trap 'rm -f -- "$manifest_tmp"; [[ -z "$settings_tmp" ]] || rm -f -- "$settings_tmp"' EXIT
render deploy/platform/postgres/db-harness.yaml "$manifest_tmp"
kubectl apply -f "$manifest_tmp"
printf 'Waiting for the four database roles and both databases\n'
kubectl -n "$PLATFORM_NAMESPACE" wait --for=jsonpath='{.status.applied}'=true \
  databaserole/harness databaserole/harness-app \
  databaserole/harness-test databaserole/harness-test-app \
  database/harness database/harness-test --timeout=300s ||
  stop "database resources are not ready; inspect Database and DatabaseRole status and re-run this script"

host="$(kubectl -n "$PLATFORM_NAMESPACE" get service ooh-pg-rw -o jsonpath='{.spec.clusterIP}')"
[[ -n "$host" && "$host" != None && "$host" != *[!0-9a-fA-F:.]* ]] ||
  stop "PostgreSQL service has no valid ClusterIP; check ooh-pg-rw"
owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret harness-test-db -o jsonpath='{.data.password}' | base64 --decode)"
app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret harness-test-app-db -o jsonpath='{.data.password}' | base64 --decode)"
[[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] ||
  stop "test database passwords have an unexpected format; inspect their Secrets privately"
settings_dir="$HOME/.config/ooh"
mkdir -p "$settings_dir"
settings_tmp="$(mktemp "$settings_dir/.harness-api-test.env.XXXXXX")"
printf "HA_TEST_DB_MIGRATE_CONNECTION='host=%s port=5432 dbname=harness_test user=harness_test password=%s'\nHA_TEST_DB_CONNECTION='host=%s port=5432 dbname=harness_test user=harness_test_app password=%s'\n" \
  "$host" "$owner_password" "$host" "$app_password" > "$settings_tmp"
chmod 600 "$settings_tmp"
mv -f -- "$settings_tmp" "$settings_dir/harness-api-test.env"
unset owner_password app_password
printf 'Test database settings saved privately in ~/.config/ooh/harness-api-test.env (mode 600)\n'
kubectl get namespace "$APPS_NAMESPACE" >/dev/null 2>&1 || stop "apps namespace missing; run platform setup first"
owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret harness-db -o jsonpath='{.data.password}' | base64 --decode)"
app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret harness-app-db -o jsonpath='{.data.password}' | base64 --decode)"
[[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] || stop "database passwords have an unexpected format; inspect their Secrets privately"
existing="$(kubectl -n "$APPS_NAMESPACE" get secret harness-api-db --ignore-not-found -o name)"
expected_connection="host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=harness user=harness_app password=$app_password"
expected_migrate="host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=harness user=harness password=$owner_password"
if [[ -n "$existing" ]]; then
  stored_connection="$(kubectl -n "$APPS_NAMESPACE" get secret harness-api-db -o jsonpath='{.data.connection}' | base64 --decode)"
  stored_migrate="$(kubectl -n "$APPS_NAMESPACE" get secret harness-api-db -o jsonpath='{.data.migrate-connection}' | base64 --decode)"
  [[ "$stored_connection" == "$expected_connection" && "$stored_migrate" == "$expected_migrate" ]] ||
    stop "existing application database credentials differ; inspect role and application Secrets privately"
else
  printf '%s\0' \
    "host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=harness user=harness_app password=$app_password" \
    "host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=harness user=harness password=$owner_password" |
    jq -Rs --arg namespace "$APPS_NAMESPACE" 'split("\u0000") as $v | {apiVersion:"v1",kind:"Secret",metadata:{name:"harness-api-db",namespace:$namespace},type:"Opaque",stringData:{connection:$v[0],"migrate-connection":$v[1]}}' |
    kubectl create -f - >/dev/null
fi
unset owner_password app_password expected_connection expected_migrate stored_connection stored_migrate
# Authentication and CLI settings remain inside the Keycloak pod.
# shellcheck disable=SC2016
client_secret="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- /bin/bash -c '
  set -euo pipefail
  set +x
  umask 077
  config_dir=$(mktemp -d /tmp/ooh-harness-setup.XXXXXXXX)
  trap '"'"'rm -rf -- "$config_dir"'"'"' EXIT
  config="$config_dir/kcadm.config"
  /opt/keycloak/bin/kcadm.sh config credentials --config "$config" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  clients=$(/opt/keycloak/bin/kcadm.sh get clients -r ooh -q clientId=ooh-harness-api --fields id,clientId --config "$config" 2>/dev/null)
  id=$(printf "%s" "$clients" | sed -n '"'"'s/.*"id"[[:space:]]*:[[:space:]]*"\([a-zA-Z0-9-]*\)".*/\1/p'"'"')
  [[ "$id" =~ ^[a-zA-Z0-9-]+$ ]]
  /opt/keycloak/bin/kcadm.sh get "clients/$id/client-secret" -r ooh --config "$config" 2>/dev/null
' 2>/dev/null | jq -ej '.value | select(type == "string" and length > 0)')" || stop "could not read Harness client secret; inspect Keycloak readiness and bootstrap access"
existing="$(kubectl -n "$APPS_NAMESPACE" get secret harness-api-oidc --ignore-not-found -o json)"
if [[ -n "$existing" ]]; then
  stored="$(jq -er '.data["client-secret"]' <<< "$existing" | base64 --decode)"
  [[ "$stored" == "$client_secret" ]] || stop "Harness client secret changed; ask the maintainer before replacing harness-api-oidc"
else
  printf '%s' "$client_secret" |
    jq -Rs --arg namespace "$APPS_NAMESPACE" '{apiVersion:"v1",kind:"Secret",metadata:{name:"harness-api-oidc",namespace:$namespace},type:"Opaque",stringData:{"client-secret":.}}' |
    kubectl create -f - >/dev/null
fi
unset client_secret stored existing
printf 'DONE\n'
