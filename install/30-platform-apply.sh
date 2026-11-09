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
[[ -f "$HOME/.config/ooh/do.env" ]] || stop "local settings missing; copy install/ooh.env.example as described in README"
# shellcheck source=/dev/null
source "$HOME/.config/ooh/do.env"
[[ -n "${LETSENCRYPT_EMAIL:-}" ]] || stop "local setting LETSENCRYPT_EMAIL is empty; fill it in as described in README"
[[ "$LETSENCRYPT_EMAIL" == *@*.* && "$LETSENCRYPT_EMAIL" != *[[:space:]]* ]] || stop "contact email is invalid; correct local settings"

[[ "$LETSENCRYPT_EMAIL" != *[\"\\]* ]] || stop "contact email contains unsupported characters; correct local settings"
[[ $# == 0 || ( $# == 1 && "$1" == --check ) ]] || stop "usage: install/30-platform-apply.sh [--check]"
for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE KAFKA_STORAGE POSTGRES_STORAGE FILES_STORAGE; do
  [[ -n "${!variable:-}" && "${!variable}" != *[!a-zA-Z0-9.-]* ]] || stop "invalid deployment value $variable; correct deploy/values/do.env"
done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
email="$(jq -Rn --arg value "$LETSENCRYPT_EMAIL" '$value')"
render() {
  local source="$1" target="$2" line variable value token
  mkdir -p "$(dirname "$target")"
  while IFS= read -r line || [[ -n "$line" ]]; do
    for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE KAFKA_STORAGE POSTGRES_STORAGE FILES_STORAGE LETSENCRYPT_EMAIL; do
      value="${!variable}"
      [[ "$variable" != LETSENCRYPT_EMAIL ]] || value="$email"
      token="\${$variable}"
      line="${line//"$token"/"$value"}"
    done
    printf '%s\n' "$line"
  done < "$source" > "$target"
}
while IFS= read -r -d '' file; do
  render "$file" "$tmp/$file"
done < <(find deploy/platform -type f -name '*.yaml' -print0)
if [[ "${1:-}" == --check ]]; then
  kubeconform -strict -summary -skip ClusterIssuer,Kafka,KafkaNodePool,KafkaTopic,KafkaUser,Cluster,DatabaseRole,Database,Keycloak,KeycloakRealmImport "$tmp/deploy/platform"
  printf 'DONE\n'
  exit 0
fi
for secret in keycloak-db keycloak-bootstrap; do
  kubectl -n "$PLATFORM_NAMESPACE" get secret "$secret" >/dev/null || stop "required secret missing; run install/20-platform-secrets.sh"
done
retain_claims() {
  local namespace="$1" selector="$2" claims volume
  claims="$(kubectl -n "$namespace" get pvc -l "$selector" -o json)"
  while IFS= read -r volume; do
    [[ -n "$volume" ]] || continue
    kubectl patch pv "$volume" --type=merge -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
  done < <(jq -r '.items[] | select(.status.phase == "Bound") | .spec.volumeName' <<< "$claims")
}
retain_existing() {
  retain_claims "$PLATFORM_NAMESPACE" strimzi.io/cluster=ooh-kafka
  retain_claims "$PLATFORM_NAMESPACE" cnpg.io/cluster=ooh-pg
  local claim volume
  claim="$(kubectl -n "$APPS_NAMESPACE" get pvc ooh-files --ignore-not-found -o json)"
  if [[ -n "$claim" ]]; then
    volume="$(jq -r 'select(.status.phase == "Bound") | .spec.volumeName' <<< "$claim")"
    [[ -z "$volume" ]] || kubectl patch pv "$volume" --type=merge -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
    # Bound claims cannot change class. Protect their PV instead of replacing them.
    existing_class="$(jq -r '.spec.storageClassName // ""' <<< "$claim")"
    [[ "$existing_class" =~ ^[a-z0-9.-]+$ ]] || stop "existing file PVC has an unsupported storage class; inspect it before retrying"
    sed -i "s/storageClassName: local-path-retain/storageClassName: $existing_class/" "$tmp/deploy/platform/storage/files-pvc.yaml"
  fi
}
kubectl apply -f "$tmp/deploy/platform/namespaces.yaml"
retain_existing
# local-path binds on first use; the storage check pod triggers provisioning.
kubectl apply -f "$tmp/deploy/platform/storage/files-pvc.yaml"
kubectl apply -f "$tmp/deploy/platform/cert-manager/cluster-issuers.template.yaml"
kubectl wait --for=condition=Ready clusterissuer/letsencrypt-staging clusterissuer/letsencrypt-prod --timeout=300s
kubectl apply -f "$tmp/deploy/platform/kafka/kafka.yaml"
printf 'Waiting for Kafka (first start can take several minutes)\n'
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready kafka/ooh-kafka --timeout=600s
kubectl apply -f "$tmp/deploy/platform/kafka/topics/"
kubectl apply -f "$tmp/deploy/platform/kafka/users/ooh-smoke.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready kafkatopic --all --timeout=300s
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready kafkauser/ooh-smoke --timeout=300s
kubectl apply -f "$tmp/deploy/platform/postgres/cluster.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready cluster.postgresql.cnpg.io/ooh-pg --timeout=600s
kubectl apply -f "$tmp/deploy/platform/postgres/db-keycloak.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=jsonpath='{.status.applied}'=true databaserole/keycloak database/keycloak --timeout=300s
kubectl apply -f "$tmp/deploy/platform/keycloak/keycloak.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready keycloak/ooh-keycloak --timeout=600s
kubectl apply -f "$tmp/deploy/platform/keycloak/realm-ooh.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Done keycloakrealmimport/ooh --timeout=300s
install/35-realm-sync.sh
retain_existing
for file in "$tmp"/deploy/platform/placeholders/*.yaml "$tmp"/deploy/platform/keycloak/ingress.yaml; do
  # A successful re-run must not request staging certificates again.
  case "$file" in
    *ingress.yaml)
      name="$(basename "$file" -ingress.yaml)"
      namespace="$APPS_NAMESPACE"
      [[ "$file" != "$tmp/deploy/platform/keycloak/ingress.yaml" ]] || { name=auth; namespace="$PLATFORM_NAMESPACE"; }
      issuer="$(kubectl -n "$namespace" get ingress "$name" -o jsonpath='{.metadata.annotations.cert-manager\.io/cluster-issuer}' --ignore-not-found)"
      if [[ "$issuer" == letsencrypt-prod ]]; then
        sed 's/letsencrypt-staging/letsencrypt-prod/' "$file" > "$tmp/ingress.yaml"
        kubectl apply -f "$tmp/ingress.yaml"
      else kubectl apply -f "$file"; fi ;;
    *) kubectl apply -f "$file" ;;
  esac
done
for name in workspace harness-api admin-console control-centre-api; do
  kubectl -n "$APPS_NAMESPACE" rollout status "deployment/$name" --timeout=300s
done
for entry in "$PLATFORM_NAMESPACE auth" "$APPS_NAMESPACE harness" "$APPS_NAMESPACE admin"; do
  read -r namespace name <<< "$entry"
  printf 'Waiting for certificate on %s (staging proves outside access)\n' "$name"
  kubectl -n "$namespace" wait --for=condition=Ready "certificate/$name-tls" --timeout=300s || stop "certificate pending for $name; check DNS points to $PUBLIC_IP and cloud firewall allows inbound TCP 80 and 443; inspect cert-manager events before retrying"
done
for entry in "$PLATFORM_NAMESPACE auth" "$APPS_NAMESPACE harness" "$APPS_NAMESPACE admin"; do
  read -r namespace name <<< "$entry"
  kubectl -n "$namespace" annotate ingress "$name" cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
  kubectl -n "$namespace" wait --for=jsonpath='{.spec.issuerRef.name}'=letsencrypt-prod "certificate/$name-tls" --timeout=120s
  # Wait for reconciliation to publish a Ready condition for the new generation.
  for ((attempt=0; attempt<150; attempt++)); do
    certificate="$(kubectl -n "$namespace" get certificate "$name-tls" -o json)"
    if jq -e '.metadata.generation as $g | any(.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $g)' <<< "$certificate" >/dev/null; then break; fi
    sleep 2
  done
  ((attempt < 150)) || stop "production certificate pending; inspect cert-manager events; if rate limited wait for the limit window"
done
printf 'DONE\n'
