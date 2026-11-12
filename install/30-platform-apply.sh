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
binding_pod=''
cleanup() {
  if [[ -n "$binding_pod" ]]; then kubectl -n "$APPS_NAMESPACE" delete pod "$binding_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; fi
  rm -rf -- "$tmp"
}
trap cleanup EXIT
# shellcheck disable=SC2034 # The renderer reads this through indirect variable expansion.
JAEGER_CONFIG_SHA256="$(sha256sum deploy/platform/tracing/configmap.yaml | cut -d ' ' -f 1)"
# shellcheck disable=SC2034 # Used by the renderer through indirect expansion.
KEYCLOAK_THEME_SHA256="$(sha256sum deploy/platform/keycloak/theme/* | sha256sum | cut -d ' ' -f 1)"
email="$(jq -Rn --arg value "$LETSENCRYPT_EMAIL" '$value')"
render() {
  local source="$1" target="$2" line variable value token
  mkdir -p "$(dirname "$target")"
  while IFS= read -r line || [[ -n "$line" ]]; do
    for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE KAFKA_STORAGE POSTGRES_STORAGE FILES_STORAGE LETSENCRYPT_EMAIL KEYCLOAK_THEME_SHA256 JAEGER_CONFIG_SHA256; do
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
kubectl -n "$PLATFORM_NAMESPACE" create configmap ooh-keycloak-theme \
  --from-file=deploy/platform/keycloak/theme/ --dry-run=client -o yaml > "$tmp/deploy/platform/keycloak/theme-configmap.yaml"
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

  fi
}
bind_files() {
  local phase
  phase="$(kubectl -n "$APPS_NAMESPACE" get pvc ooh-files -o jsonpath='{.status.phase}')"
  [[ "$phase" != Bound ]] || return 0
  # local-path waits for a first consumer before creating the PV we must protect.
  binding_pod="ooh-files-bind-$(date +%s)-$RANDOM"
  printf 'Waiting for the file claim to bind before setting its PV to Retain\n'
  jq -n --arg name "$binding_pod" --arg namespace "$APPS_NAMESPACE" '{apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:$namespace},spec:{restartPolicy:"Never",activeDeadlineSeconds:120,automountServiceAccountToken:false,securityContext:{runAsNonRoot:true,runAsUser:1001,runAsGroup:1001,fsGroup:1001,seccompProfile:{type:"RuntimeDefault"}},containers:[{name:"bind",image:"ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie",command:["/bin/bash","-c","true"],resources:{requests:{cpu:"10m",memory:"32Mi"},limits:{cpu:"100m",memory:"64Mi"}},securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"files",mountPath:"/files"}]}],volumes:[{name:"files",persistentVolumeClaim:{claimName:"ooh-files"}}]}}' | kubectl create -f - >/dev/null
  kubectl -n "$APPS_NAMESPACE" wait --for=jsonpath='{.status.phase}'=Succeeded "pod/$binding_pod" --timeout=150s || stop "file claim binding failed; inspect ooh-files PVC and local-path provisioner before retrying"
  kubectl -n "$APPS_NAMESPACE" wait --for=jsonpath='{.status.phase}'=Bound pvc/ooh-files --timeout=30s
  kubectl -n "$APPS_NAMESPACE" delete pod "$binding_pod" --ignore-not-found --wait=false >/dev/null
  binding_pod=''
}
wait_keycloak() {
  local deadline=$((SECONDS + 600)) resources
  printf 'Waiting for Keycloak and its current pod revision to be Ready\n'
  while ((SECONDS < deadline)); do
    # Read fresh objects each time: a replaced pod can be Failed, terminating or temporarily absent.
    if resources="$(kubectl -n "$PLATFORM_NAMESPACE" --request-timeout=10s get keycloak/ooh-keycloak statefulset/ooh-keycloak pod/ooh-keycloak-0 --ignore-not-found -o json 2>/dev/null)" &&
      jq -e '
        ([.items[]? | select(.kind == "Keycloak")][0] // {}) as $cr |
        ([.items[]? | select(.kind == "StatefulSet")][0] // {}) as $sts |
        ([.items[]? | select(.kind == "Pod")][0] // {}) as $pod |
        ($cr.metadata.deletionTimestamp == null) and
        ($cr.metadata.generation != null) and
        ($cr.status.observedGeneration == $cr.metadata.generation) and
        any($cr.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $cr.metadata.generation) and
        ($sts.metadata.deletionTimestamp == null) and
        ($sts.metadata.generation != null) and
        (($sts.status.observedGeneration // 0) >= $sts.metadata.generation) and
        (($sts.status.updateRevision // "") != "") and
        ($sts.status.currentRevision == $sts.status.updateRevision) and
        ($sts.status.readyReplicas == $sts.spec.replicas) and
        ($sts.status.updatedReplicas == $sts.spec.replicas) and
        ($pod.metadata.deletionTimestamp == null) and
        ($pod.status.phase == "Running") and
        ($pod.metadata.labels["controller-revision-hash"] == $sts.status.updateRevision) and
        any($pod.status.conditions[]?; .type == "Ready" and .status == "True")
      ' <<< "$resources" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  stop "Keycloak rollout is not Ready on the current revision after 10 minutes; inspect the Keycloak CR, StatefulSet and pod, then re-run step 6"
}
kubectl apply -f "$tmp/deploy/platform/namespaces.yaml"
kubectl apply -f "$tmp/deploy/platform/tracing/"
kubectl -n "$PLATFORM_NAMESPACE" rollout status deployment/jaeger --timeout=300s
retain_existing
# Bind a fresh file claim before protecting its PV.
kubectl apply -f "$tmp/deploy/platform/storage/files-pvc.yaml"
bind_files
retain_existing
kubectl apply -f "$tmp/deploy/platform/cert-manager/cluster-issuers.template.yaml"
kubectl wait --for=condition=Ready clusterissuer/letsencrypt-staging clusterissuer/letsencrypt-prod --timeout=300s
kubectl apply -f "$tmp/deploy/platform/kafka/kafka.yaml"
printf 'Waiting for Kafka (first start can take several minutes)\n'
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready kafka/ooh-kafka --timeout=600s
retain_claims "$PLATFORM_NAMESPACE" strimzi.io/cluster=ooh-kafka
kubectl apply -f "$tmp/deploy/platform/kafka/topics/"
kubectl apply -f "$tmp/deploy/platform/kafka/users/"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready kafkatopic --all --timeout=300s
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready kafkauser --all --timeout=300s
kubectl apply -f "$tmp/deploy/platform/postgres/cluster.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Ready cluster.postgresql.cnpg.io/ooh-pg --timeout=600s
retain_claims "$PLATFORM_NAMESPACE" cnpg.io/cluster=ooh-pg
kubectl apply -f "$tmp/deploy/platform/postgres/db-keycloak.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=jsonpath='{.status.applied}'=true databaserole/keycloak database/keycloak --timeout=300s
kubectl apply -f "$tmp/deploy/platform/keycloak/theme-configmap.yaml"
kubectl apply -f "$tmp/deploy/platform/keycloak/keycloak.yaml"
wait_keycloak
kubectl apply -f "$tmp/deploy/platform/keycloak/realm-ooh.yaml"
kubectl -n "$PLATFORM_NAMESPACE" wait --for=condition=Done keycloakrealmimport/ooh --timeout=300s
wait_keycloak
install/35-realm-sync.sh
retain_existing
for file in "$tmp"/deploy/platform/placeholders/*.yaml "$tmp"/deploy/platform/keycloak/ingress.yaml; do
  [[ "$file" != "$tmp/deploy/platform/placeholders/control-centre-api.yaml" ]] || continue
  case "$(basename "$file")" in
    workspace.yaml|harness-api.yaml|admin-console.yaml)
      name="$(basename "$file" .yaml)"
      deployment="$(kubectl -n "$APPS_NAMESPACE" get deployment "$name" --ignore-not-found -o json)"
      if [[ -n "$deployment" ]] && jq -e '.spec.template.metadata.labels["ooh/app"] == "real"' <<< "$deployment" >/dev/null; then
        continue
      fi ;;
  esac
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
for name in workspace harness-api admin-console; do
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
