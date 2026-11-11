#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# shellcheck disable=SC2016 # Quoted commands expand only inside the Keycloak pod.
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "database setup failed; inspect PostgreSQL readiness and re-run install/74-consumers-setup.sh"' ERR
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
[[ $# == 0 ]] || stop "usage: install/74-consumers-setup.sh"
for tool in kubectl jq openssl base64 mktemp sed; do
  command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"
done
kubectl get namespace "$PLATFORM_NAMESPACE" >/dev/null 2>&1 || stop "platform namespace missing; run install/30-platform-apply.sh first"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready cluster.postgresql.cnpg.io/ooh-pg --timeout=300s ||
  stop "PostgreSQL is not Ready; check the platform before retrying"

(
for name in auditwriter auditwriter-app auditwriter-test auditwriter-test-app; do
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
render deploy/platform/postgres/db-auditwriter.yaml "$manifest_tmp"
kubectl apply -f "$manifest_tmp"
printf 'Waiting for the four database roles and both databases\n'
kubectl -n "$PLATFORM_NAMESPACE" wait --for=jsonpath='{.status.applied}'=true \
  databaserole/auditwriter databaserole/auditwriter-app \
  databaserole/auditwriter-test databaserole/auditwriter-test-app \
  database/auditwriter database/auditwriter-test --timeout=300s ||
  stop "database resources are not ready; inspect Database and DatabaseRole status and re-run this script"

host="$(kubectl -n "$PLATFORM_NAMESPACE" get service ooh-pg-rw -o jsonpath='{.spec.clusterIP}')"
[[ -n "$host" && "$host" != None && "$host" != *[!0-9a-fA-F:.]* ]] ||
  stop "PostgreSQL service has no valid ClusterIP; check ooh-pg-rw"
owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret auditwriter-test-db -o jsonpath='{.data.password}' | base64 --decode)"
app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret auditwriter-test-app-db -o jsonpath='{.data.password}' | base64 --decode)"
[[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] ||
  stop "test database passwords have an unexpected format; inspect their Secrets privately"
settings_dir="$HOME/.config/ooh"
mkdir -p "$settings_dir"
settings_tmp="$(mktemp "$settings_dir/.audit-writer-test.env.XXXXXX")"
printf "AW_TEST_DB_MIGRATE_CONNECTION='host=%s port=5432 dbname=auditwriter_test user=auditwriter_test password=%s'\nAW_TEST_DB_CONNECTION='host=%s port=5432 dbname=auditwriter_test user=auditwriter_test_app password=%s'\n" \
  "$host" "$owner_password" "$host" "$app_password" > "$settings_tmp"
chmod 600 "$settings_tmp"
mv -f -- "$settings_tmp" "$settings_dir/audit-writer-test.env"
unset owner_password app_password
printf 'Test database settings saved privately in ~/.config/ooh/audit-writer-test.env (mode 600)\n'
existing="$(kubectl -n "$APPS_NAMESPACE" get secret audit-writer-db --ignore-not-found -o name)"
if [[ -z "$existing" ]]; then
  owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret auditwriter-db -o jsonpath='{.data.password}' | base64 --decode)"
  app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret auditwriter-app-db -o jsonpath='{.data.password}' | base64 --decode)"
  [[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] || stop "database passwords have an unexpected format; inspect role Secrets privately"
  printf '%s\0' \
    "host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=auditwriter user=auditwriter_app password=$app_password" \
    "host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=auditwriter user=auditwriter password=$owner_password" |
    jq -Rs --arg namespace "$APPS_NAMESPACE" 'split("\u0000") as $v | {apiVersion:"v1",kind:"Secret",metadata:{name:"audit-writer-db",namespace:$namespace},type:"Opaque",stringData:{connection:$v[0],"migrate-connection":$v[1]}}' |
    kubectl create -f - >/dev/null
  unset owner_password app_password
fi

)
(
for name in costmeter costmeter-app costmeter-test costmeter-test-app; do
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
render deploy/platform/postgres/db-costmeter.yaml "$manifest_tmp"
kubectl apply -f "$manifest_tmp"
printf 'Waiting for the four database roles and both databases\n'
kubectl -n "$PLATFORM_NAMESPACE" wait --for=jsonpath='{.status.applied}'=true \
  databaserole/costmeter databaserole/costmeter-app \
  databaserole/costmeter-test databaserole/costmeter-test-app \
  database/costmeter database/costmeter-test --timeout=300s ||
  stop "database resources are not ready; inspect Database and DatabaseRole status and re-run this script"

host="$(kubectl -n "$PLATFORM_NAMESPACE" get service ooh-pg-rw -o jsonpath='{.spec.clusterIP}')"
[[ -n "$host" && "$host" != None && "$host" != *[!0-9a-fA-F:.]* ]] ||
  stop "PostgreSQL service has no valid ClusterIP; check ooh-pg-rw"
owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret costmeter-test-db -o jsonpath='{.data.password}' | base64 --decode)"
app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret costmeter-test-app-db -o jsonpath='{.data.password}' | base64 --decode)"
[[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] ||
  stop "test database passwords have an unexpected format; inspect their Secrets privately"
settings_dir="$HOME/.config/ooh"
mkdir -p "$settings_dir"
settings_tmp="$(mktemp "$settings_dir/.cost-meter-test.env.XXXXXX")"
printf "CM_TEST_DB_MIGRATE_CONNECTION='host=%s port=5432 dbname=costmeter_test user=costmeter_test password=%s'\nCM_TEST_DB_CONNECTION='host=%s port=5432 dbname=costmeter_test user=costmeter_test_app password=%s'\n" \
  "$host" "$owner_password" "$host" "$app_password" > "$settings_tmp"
chmod 600 "$settings_tmp"
mv -f -- "$settings_tmp" "$settings_dir/cost-meter-test.env"
unset owner_password app_password
printf 'Test database settings saved privately in ~/.config/ooh/cost-meter-test.env (mode 600)\n'
existing="$(kubectl -n "$APPS_NAMESPACE" get secret cost-meter-db --ignore-not-found -o name)"
if [[ -z "$existing" ]]; then
  owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret costmeter-db -o jsonpath='{.data.password}' | base64 --decode)"
  app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret costmeter-app-db -o jsonpath='{.data.password}' | base64 --decode)"
  [[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] || stop "database passwords have an unexpected format; inspect role Secrets privately"
  printf '%s\0' \
    "host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=costmeter user=costmeter_app password=$app_password" \
    "host=ooh-pg-rw.$PLATFORM_NAMESPACE.svc port=5432 dbname=costmeter user=costmeter password=$owner_password" |
    jq -Rs --arg namespace "$APPS_NAMESPACE" 'split("\u0000") as $v | {apiVersion:"v1",kind:"Secret",metadata:{name:"cost-meter-db",namespace:$namespace},type:"Opaque",stringData:{connection:$v[0],"migrate-connection":$v[1]}}' |
    kubectl create -f - >/dev/null
  unset owner_password app_password
fi

)
# Bootstrap credentials and the temporary CLI configuration stay inside Keycloak.
client_secret="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- bash -c '
  set -euo pipefail
  set +x
  umask 077
  private_dir=$(mktemp -d /tmp/ooh-safety-setup.XXXXXXXX)
  trap '\''rm -rf -- "$private_dir"'\'' EXIT
  cli=/opt/keycloak/bin/kcadm.sh
  "$cli" config credentials --config "$private_dir/config" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  clients=$("$cli" get clients -r ooh -q clientId=ooh-safety-watcher --fields id,clientId --config "$private_dir/config" 2>/dev/null)
  printf "%s" "$clients"
  id=$(printf "%s" "$clients" | sed -n '\''s/.*"id" *: *"\([^" ]*\)".*/\1/p'\'')
  [[ "$id" =~ ^[a-f0-9-]{36}$ ]]
  "$cli" get "clients/$id/client-secret" -r ooh --config "$private_dir/config" 2>/dev/null
')" || stop "could not read Safety watcher client secret; check Keycloak bootstrap access"
client_secret="$(printf '%s' "$client_secret" | jq -s -ej '.[1].value | select(type == "string" and length > 0)')" || stop "Safety watcher client secret missing; inspect the realm client"
existing="$(kubectl -n "$APPS_NAMESPACE" get secret safety-watcher-oidc --ignore-not-found -o json)"
if [[ -n "$existing" ]]; then
  stored="$(printf '%s' "$existing" | jq -r '.data["client-secret"] // ""')"
  current="$(printf '%s' "$client_secret" | base64 -w0)"
  [[ "$stored" == "$current" ]] || stop "Safety watcher client secret changed; ask the maintainer before replacing safety-watcher-oidc"
else
  printf '%s' "$client_secret" |
    jq -Rs --arg namespace "$APPS_NAMESPACE" '{apiVersion:"v1",kind:"Secret",metadata:{name:"safety-watcher-oidc",namespace:$namespace},type:"Opaque",stringData:{"client-secret":.}}' |
    kubectl create -f - >/dev/null
fi
unset client_secret stored current existing
for name in audit-writer cost-meter safety-watcher; do
  deadline=$((SECONDS + 120))
  while :; do
    ready="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkauser "$name" -o json 2>/dev/null || true)"
    kafka_secret="$(kubectl -n "$PLATFORM_NAMESPACE" get secret "$name" -o json 2>/dev/null || true)"
    if jq -e 'any(.status.conditions[]?; .type == "Ready" and .status == "True")' <<< "$ready" >/dev/null 2>&1 &&
       jq -e '.data.password | type == "string" and length > 0' <<< "$kafka_secret" >/dev/null 2>&1; then break; fi
    (( SECONDS < deadline )) || stop "KafkaUser $name not ready; re-run 30"
    sleep 2
  done
  password="$(jq -r '.data.password' <<< "$kafka_secret")"
  existing="$(kubectl -n "$APPS_NAMESPACE" get secret "$name-kafka" --ignore-not-found -o json)"
  if [[ -n "$existing" ]]; then
    stored="$(jq -r '.data.password // ""' <<< "$existing")"
    [[ "$stored" == "$password" ]] || stop "Kafka password changed for $name; inspect the Secret privately before replacing it"
  else
    printf '%s' "$password" | jq -Rs --arg name "$name-kafka" --arg namespace "$APPS_NAMESPACE" \
      '{apiVersion:"v1",kind:"Secret",metadata:{name:$name,namespace:$namespace},type:"Opaque",data:{password:.}}' |
      kubectl create -f - >/dev/null
  fi
  unset password stored kafka_secret existing ready
done
printf 'DONE\n'
