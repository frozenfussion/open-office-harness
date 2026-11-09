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
for secret in keycloak-db keycloak-bootstrap; do
  kubectl -n ooh-platform get secret "$secret" >/dev/null || stop "required secret missing; run install/20-platform-secrets.sh"
done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
# The email is non-secret; jq produces a correctly quoted YAML scalar.
email="$(jq -Rn --arg value "$LETSENCRYPT_EMAIL" '$value')"
while IFS= read -r line; do
  printf '%s\n' "${line//\$\{LETSENCRYPT_EMAIL\}/$email}"
done < deploy/platform/cert-manager/cluster-issuers.template.yaml > "$tmp/issuers.yaml"
kubectl apply -f deploy/platform/namespaces.yaml
# local-path binds on first use; the storage check pod triggers provisioning.
kubectl apply -f deploy/platform/storage/files-pvc.yaml
kubectl apply -f "$tmp/issuers.yaml"
kubectl wait --for=condition=Ready clusterissuer/letsencrypt-staging clusterissuer/letsencrypt-prod --timeout=300s
kubectl apply -f deploy/platform/kafka/kafka.yaml
printf 'Waiting for Kafka (first start can take several minutes)\n'
kubectl -n ooh-platform wait --for=condition=Ready kafka/ooh-kafka --timeout=600s
kubectl apply -f deploy/platform/kafka/topics/
kubectl apply -f deploy/platform/kafka/users/ooh-smoke.yaml
kubectl -n ooh-platform wait --for=condition=Ready kafkatopic --all --timeout=300s
kubectl -n ooh-platform wait --for=condition=Ready kafkauser/ooh-smoke --timeout=300s
kubectl apply -f deploy/platform/postgres/cluster.yaml
kubectl -n ooh-platform wait --for=condition=Ready cluster.postgresql.cnpg.io/ooh-pg --timeout=600s
kubectl apply -f deploy/platform/postgres/db-keycloak.yaml
kubectl -n ooh-platform wait --for=jsonpath='{.status.applied}'=true databaserole/keycloak database/keycloak --timeout=300s
kubectl apply -f deploy/platform/keycloak/keycloak.yaml
kubectl -n ooh-platform wait --for=condition=Ready keycloak/ooh-keycloak --timeout=600s
kubectl apply -f deploy/platform/keycloak/realm-ooh.yaml
kubectl -n ooh-platform wait --for=condition=Done keycloakrealmimport/ooh --timeout=300s
for file in deploy/platform/placeholders/*.yaml deploy/platform/keycloak/ingress.yaml; do
  # A successful re-run must not request staging certificates again.
  case "$file" in
    *ingress.yaml)
      name="$(basename "$file" -ingress.yaml)"
      namespace=ooh-apps
      [[ "$file" != deploy/platform/keycloak/ingress.yaml ]] || { name=auth; namespace=ooh-platform; }
      issuer="$(kubectl -n "$namespace" get ingress "$name" -o jsonpath='{.metadata.annotations.cert-manager\.io/cluster-issuer}' --ignore-not-found)"
      if [[ "$issuer" == letsencrypt-prod ]]; then
        sed 's/letsencrypt-staging/letsencrypt-prod/' "$file" > "$tmp/ingress.yaml"
        kubectl apply -f "$tmp/ingress.yaml"
      else kubectl apply -f "$file"; fi ;;
    *) kubectl apply -f "$file" ;;
  esac
done
for name in workspace harness-api admin-console control-centre-api; do
  kubectl -n ooh-apps rollout status "deployment/$name" --timeout=300s
done
for entry in 'ooh-platform auth' 'ooh-apps harness' 'ooh-apps admin'; do
  read -r namespace name <<< "$entry"
  printf 'Waiting for certificate on %s (staging proves outside access)\n' "$name"
  kubectl -n "$namespace" wait --for=condition=Ready "certificate/$name-tls" --timeout=300s || stop "certificate pending for $name; check DNS points to $PUBLIC_IP and cloud firewall allows inbound TCP 80 and 443; inspect cert-manager events before retrying"
done
for entry in 'ooh-platform auth' 'ooh-apps harness' 'ooh-apps admin'; do
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
