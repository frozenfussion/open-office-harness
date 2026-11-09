#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "database setup failed; inspect PostgreSQL readiness and re-run install/59-control-centre-databases.sh"' ERR
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
[[ $# == 0 ]] || stop "usage: install/59-control-centre-databases.sh"
for tool in kubectl jq openssl base64 mktemp; do
  command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"
done
kubectl get namespace "$PLATFORM_NAMESPACE" >/dev/null 2>&1 || stop "platform namespace missing; run install/30-platform-apply.sh first"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready cluster.postgresql.cnpg.io/ooh-pg --timeout=300s ||
  stop "PostgreSQL is not Ready; check the platform before retrying"

for name in controlcentre controlcentre-app controlcentre-test controlcentre-test-app; do
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
render deploy/platform/postgres/db-controlcentre.yaml "$manifest_tmp"
kubectl apply -f "$manifest_tmp"
printf 'Waiting for the four database roles and both databases\n'
kubectl -n "$PLATFORM_NAMESPACE" wait --for=jsonpath='{.status.applied}'=true \
  databaserole/controlcentre databaserole/controlcentre-app \
  databaserole/controlcentre-test databaserole/controlcentre-test-app \
  database/controlcentre database/controlcentre-test --timeout=300s ||
  stop "database resources are not ready; inspect Database and DatabaseRole status and re-run this script"

host="$(kubectl -n "$PLATFORM_NAMESPACE" get service ooh-pg-rw -o jsonpath='{.spec.clusterIP}')"
[[ -n "$host" && "$host" != None && "$host" != *[!0-9a-fA-F:.]* ]] ||
  stop "PostgreSQL service has no valid ClusterIP; check ooh-pg-rw"
owner_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret controlcentre-test-db -o jsonpath='{.data.password}' | base64 --decode)"
app_password="$(kubectl -n "$PLATFORM_NAMESPACE" get secret controlcentre-test-app-db -o jsonpath='{.data.password}' | base64 --decode)"
[[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] ||
  stop "test database passwords have an unexpected format; inspect their Secrets privately"
settings_dir="$HOME/.config/ooh"
mkdir -p "$settings_dir"
settings_tmp="$(mktemp "$settings_dir/.control-centre-test.env.XXXXXX")"
printf "CC_TEST_DB_MIGRATE_CONNECTION='Host=%s;Port=5432;Database=controlcentre_test;Username=controlcentre_test;Password=%s'\nCC_TEST_DB_CONNECTION='Host=%s;Port=5432;Database=controlcentre_test;Username=controlcentre_test_app;Password=%s'\n" \
  "$host" "$owner_password" "$host" "$app_password" > "$settings_tmp"
chmod 600 "$settings_tmp"
mv -f -- "$settings_tmp" "$settings_dir/control-centre-test.env"
unset owner_password app_password
printf 'Test database settings saved privately in ~/.config/ooh/control-centre-test.env (mode 600)\n'
printf 'DONE\n'
