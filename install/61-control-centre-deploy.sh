#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Control Centre deployment failed; inspect migration logs and pod readiness, then re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# -le 1 ]] || stop "usage: install/61-control-centre-deploy.sh [12-character-image-tag]"
for tool in kubectl curl jq git sed mktemp; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
tag="${1:-$(git rev-parse --short=12 HEAD)}"
[[ "$tag" =~ ^[a-f0-9]{12}$ ]] || stop "image tag must be the first 12 characters of the image commit hash"
image="ghcr.io/frozenfussion/ooh-control-centre:$tag"
# A public registry token is anonymous and is supplied to curl on stdin.
registry_reply="$(curl --connect-timeout 10 --max-time 30 -fsS 'https://ghcr.io/token?service=ghcr.io&scope=repository:frozenfussion/ooh-control-centre:pull' 2>/dev/null)" ||
  stop "image not built yet; run the workflow for this commit"
registry_token="$(printf '%s' "$registry_reply" | jq -er '.token // .access_token')"
[[ "$registry_token" =~ ^[a-zA-Z0-9._~+/-]+=*$ ]] || stop "registry returned an invalid token; retry the image check"
status="$(printf 'header = "Authorization: Bearer %s"\n' "$registry_token" |
  curl --config - --connect-timeout 10 --max-time 30 -sS -o /dev/null -w '%{http_code}' \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/frozenfussion/ooh-control-centre/manifests/$tag" 2>/dev/null)" ||
  stop "image not built yet; run the workflow for this commit"
unset registry_reply registry_token
[[ "$status" == 200 ]] || stop "image not built yet; run the workflow for this commit"
for secret in control-centre-db control-centre-kafka; do
  kubectl -n ooh-apps get secret "$secret" >/dev/null 2>&1 || stop "required application secret missing; run install/60-control-centre-secrets.sh"
done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/apps"
for file in deploy/apps/control-centre/*.yaml; do
  sed "s/\${IMAGE_TAG}/$tag/g" "$file" > "$tmp/apps/$(basename "$file")"
done
# Keep the existing production issuer when re-applying the certificate-owning Ingress.
issuer="$(kubectl -n ooh-apps get ingress admin -o jsonpath='{.metadata.annotations.cert-manager\.io/cluster-issuer}')"
[[ "$issuer" == letsencrypt-prod || "$issuer" == letsencrypt-staging ]] || stop "admin Ingress has an unexpected certificate issuer; inspect it before deploying"
# shellcheck disable=SC2016 # Replace literal template tokens.
sed -e 's/${APPS_NAMESPACE}/ooh-apps/g' -e 's/${DOMAIN}/faysalaziz.com/g' \
  -e "s/letsencrypt-staging/$issuer/" deploy/platform/placeholders/admin-ingress.yaml > "$tmp/admin-ingress.yaml"
kubectl apply -f "$tmp/admin-ingress.yaml"
kubectl apply -f "$tmp/apps/configmap.yaml" -f "$tmp/apps/service.yaml" -f "$tmp/apps/deployment.yaml" -f "$tmp/apps/ingress.yaml"
printf 'Waiting for migrations and the new Control Centre pod revision (%s)\n' "$tag"
kubectl -n ooh-apps rollout status deployment/control-centre --timeout=600s ||
  stop "new Control Centre revision is not Ready; inspect the migrate container logs and image visibility"
resources="$(kubectl -n ooh-apps get deployment,replicaset,pod -l app=control-centre -o json)"
jq -e --arg image "$image" '
  ([.items[] | select(.kind == "Deployment" and .metadata.name == "control-centre")][0]) as $d |
  ($d.metadata.annotations["deployment.kubernetes.io/revision"]) as $revision |
  [.items[] | select(.kind == "ReplicaSet" and .metadata.annotations["deployment.kubernetes.io/revision"] == $revision)
    | select(any(.metadata.ownerReferences[]?; .uid == $d.metadata.uid)) | .metadata.uid] as $rs |
  $d.status.observedGeneration == $d.metadata.generation and
  $d.status.updatedReplicas == 1 and $d.status.readyReplicas == 1 and
  any(.items[]; .kind == "Pod" and .metadata.deletionTimestamp == null and
    any(.metadata.ownerReferences[]?; .uid as $uid | $rs | index($uid) != null) and
    any(.status.conditions[]?; .type == "Ready" and .status == "True") and
    any(.status.initContainerStatuses[]?; .name == "migrate" and .state.terminated.exitCode == 0) and
    any(.spec.containers[]; .name == "control-centre" and .image == $image))
' <<< "$resources" >/dev/null || stop "current revision or migrations could not be verified; inspect the deployment and pods"
kubectl -n ooh-apps delete deployment/control-centre-api service/control-centre-api --ignore-not-found
printf 'Running image: %s\nDONE\n' "$image"
