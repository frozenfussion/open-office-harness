#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "step failed; see README troubleshooting and re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in kubectl curl sed; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
fetch() {
  local url="$1" target="$2" status
  status="$(curl --connect-timeout 15 --max-time 120 -sSL -w '%{http_code}' -o "$target" "$url")" || stop "$url not found"
  [[ "$status" == 200 ]] || stop "$url not found"
}
kubectl apply -f deploy/platform/namespaces.yaml
fetch https://github.com/cert-manager/cert-manager/releases/download/v1.21.3/cert-manager.yaml "$tmp/cert.yaml"
kubectl apply --server-side -f "$tmp/cert.yaml"
for name in cert-manager cert-manager-cainjector cert-manager-webhook; do
  kubectl -n cert-manager rollout status "deployment/$name" --timeout=300s
done
STRIMZI_BASE=https://raw.githubusercontent.com/strimzi/strimzi-kafka-operator/1.3.1/packaging/install/cluster-operator
for file in \
  010-ServiceAccount-strimzi-cluster-operator.yaml \
  020-ClusterRole-strimzi-cluster-operator-role.yaml \
  020-RoleBinding-strimzi-cluster-operator.yaml \
  021-ClusterRole-strimzi-cluster-operator-role.yaml \
  021-ClusterRoleBinding-strimzi-cluster-operator.yaml \
  022-ClusterRole-strimzi-cluster-operator-role.yaml \
  022-RoleBinding-strimzi-cluster-operator.yaml \
  023-ClusterRole-strimzi-cluster-operator-role.yaml \
  023-RoleBinding-strimzi-cluster-operator.yaml \
  030-ClusterRole-strimzi-kafka-broker.yaml \
  030-ClusterRoleBinding-strimzi-cluster-operator-kafka-broker-delegation.yaml \
  031-ClusterRole-strimzi-entity-operator.yaml \
  031-RoleBinding-strimzi-cluster-operator-entity-operator-delegation.yaml \
  033-ClusterRole-strimzi-kafka-client.yaml \
  033-ClusterRoleBinding-strimzi-cluster-operator-kafka-client-delegation.yaml \
  040-Crd-kafka.yaml \
  041-Crd-kafkaconnect.yaml \
  042-Crd-strimzipodset.yaml \
  043-Crd-kafkatopic.yaml \
  044-Crd-kafkauser.yaml \
  045-Crd-kafkanodepool.yaml \
  046-Crd-kafkabridge.yaml \
  047-Crd-kafkaconnector.yaml \
  048-Crd-kafkamirrormaker2.yaml \
  049-Crd-kafkarebalance.yaml \
  050-ConfigMap-strimzi-cluster-operator.yaml \
  060-Deployment-strimzi-cluster-operator.yaml; do
  fetch "$STRIMZI_BASE/$file" "$tmp/strimzi.yaml"
  sed 's/namespace: .*/namespace: ooh-platform/' "$tmp/strimzi.yaml" > "$tmp/scoped.yaml"
  kubectl -n ooh-platform apply --server-side -f "$tmp/scoped.yaml"
done
kubectl -n ooh-platform rollout status deployment/strimzi-cluster-operator --timeout=300s
fetch https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/v1.30.0/releases/cnpg-1.30.0.yaml "$tmp/cnpg.yaml"
kubectl apply --server-side -f "$tmp/cnpg.yaml"
kubectl -n cnpg-system rollout status deployment/cnpg-controller-manager --timeout=300s
KEYCLOAK_BASE=https://raw.githubusercontent.com/keycloak/keycloak-k8s-resources/26.8.2/kubernetes
for file in keycloaks.k8s.keycloak.org-v1.yml keycloakrealmimports.k8s.keycloak.org-v1.yml keycloaksamlclients.k8s.keycloak.org-v1.yml keycloakoidcclients.k8s.keycloak.org-v1.yml; do
  fetch "$KEYCLOAK_BASE/$file" "$tmp/crd.yaml"
  kubectl apply --server-side -f "$tmp/crd.yaml"
done
fetch "$KEYCLOAK_BASE/kubernetes.yml" "$tmp/operator.yaml"
kubectl -n ooh-platform apply --server-side -f "$tmp/operator.yaml"
kubectl -n ooh-platform rollout status deployment/keycloak-operator --timeout=300s
printf 'DONE\n'
