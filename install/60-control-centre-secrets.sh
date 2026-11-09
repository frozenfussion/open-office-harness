#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "secret setup failed; check platform readiness and re-run install/60-control-centre-secrets.sh"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# == 0 ]] || stop "usage: install/60-control-centre-secrets.sh"
for tool in kubectl jq base64; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
kubectl get namespace ooh-apps >/dev/null 2>&1 || stop "apps namespace missing; run platform setup first"
kubectl -n ooh-platform wait --for=jsonpath='{.status.applied}'=true \
  database/controlcentre databaserole/controlcentre databaserole/controlcentre-app --timeout=60s ||
  stop "live database is not ready; run install/59-control-centre-databases.sh first"
for name in control-centre ooh-stage-check; do
  kubectl apply -f "deploy/platform/kafka/users/$name.yaml"
  kubectl -n ooh-platform wait --for=condition=Ready "kafkauser/$name" --timeout=300s ||
    stop "Kafka user $name is not Ready; inspect KafkaUser status and retry"
  deadline=$((SECONDS + 60))
  while :; do
    password="$(kubectl -n ooh-platform get secret "$name" --ignore-not-found -o jsonpath='{.data.password}')"
    [[ -z "$password" ]] || break
    ((SECONDS < deadline)) || stop "Kafka password for $name is missing; inspect Strimzi and re-run this script"
    sleep 2
  done
  unset password
done
existing="$(kubectl -n ooh-apps get secret control-centre-db --ignore-not-found -o name)"
if [[ -n "$existing" ]]; then
  printf 'Already exists: control-centre-db (kept)\n'
else
  owner_password="$(kubectl -n ooh-platform get secret controlcentre-db -o jsonpath='{.data.password}' | base64 --decode)"
  app_password="$(kubectl -n ooh-platform get secret controlcentre-app-db -o jsonpath='{.data.password}' | base64 --decode)"
  [[ "$owner_password" =~ ^[a-f0-9]{64}$ && "$app_password" =~ ^[a-f0-9]{64}$ ]] ||
    stop "database passwords have an unexpected format; inspect the role Secrets privately"
  printf '%s\0' \
    "Host=ooh-pg-rw.ooh-platform.svc;Port=5432;Database=controlcentre;Username=controlcentre_app;Password=$app_password" \
    "Host=ooh-pg-rw.ooh-platform.svc;Port=5432;Database=controlcentre;Username=controlcentre;Password=$owner_password" |
    jq -Rs 'split("\u0000") as $v | {apiVersion:"v1",kind:"Secret",metadata:{name:"control-centre-db",namespace:"ooh-apps"},type:"Opaque",stringData:{connection:$v[0],"migrate-connection":$v[1]}}' |
    kubectl create -f - >/dev/null
  unset owner_password app_password
  printf 'Created control-centre-db\n'
fi
existing="$(kubectl -n ooh-apps get secret control-centre-kafka --ignore-not-found -o name)"
if [[ -n "$existing" ]]; then
  printf 'Already exists: control-centre-kafka (kept)\n'
else
  # Preserve the encoded value so no password needs to become a process argument.
  kubectl -n ooh-platform get secret control-centre -o json |
    jq -e 'if (.data.password // "") == "" then error("Kafka password missing") else
      {apiVersion:"v1",kind:"Secret",metadata:{name:"control-centre-kafka",namespace:"ooh-apps"},type:"Opaque",data:{password:.data.password}} end' |
    kubectl create -f - >/dev/null
  printf 'Created control-centre-kafka\n'
fi
printf 'DONE\n'
