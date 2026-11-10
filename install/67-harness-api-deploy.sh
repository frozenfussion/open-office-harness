#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Harness API deployment failed; inspect migration logs and pod readiness, then re-run this script"' ERR
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
[[ $# -le 1 ]] || stop "usage: install/67-harness-api-deploy.sh [12-character-image-tag]"
for tool in kubectl curl jq git sed mktemp sha256sum; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
tag="${1:-$(git rev-parse --short=12 HEAD)}"
[[ "$tag" =~ ^[a-f0-9]{12}$ ]] || stop "image tag must be the first 12 characters of the image commit hash"
image="ghcr.io/frozenfussion/ooh-harness-api:$tag"
check_registry_status() {
  case "$1" in
    200) ;;
    404) stop "image not built yet; run the workflow for this commit" ;;
    401|403) stop "image not found or not public; check that the workflow run for this commit is green, then switch the ooh-harness-api package to Public (see services/harness-api/README.md)" ;;
    *) stop "registry check failed with HTTP $1; check ghcr.io availability and retry" ;;
  esac
}
# A public registry token is anonymous and is supplied to curl on stdin.
registry_response="$(curl --connect-timeout 10 --max-time 30 -sS -w '\n%{http_code}' 'https://ghcr.io/token?service=ghcr.io&scope=repository:frozenfussion/ooh-harness-api:pull' 2>/dev/null)" ||
  stop "registry is unreachable; check ghcr.io availability and retry"
check_registry_status "${registry_response##*$'\n'}"
registry_reply="${registry_response%$'\n'*}"
registry_token="$(printf '%s' "$registry_reply" | jq -er '.token // .access_token')"
[[ "$registry_token" =~ ^[a-zA-Z0-9._~+/-]+=*$ ]] || stop "registry returned an invalid token; retry the image check"
status="$(printf 'header = "Authorization: Bearer %s"\n' "$registry_token" |
  curl --config - --connect-timeout 10 --max-time 30 -sS -o /dev/null -w '%{http_code}' \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/frozenfussion/ooh-harness-api/manifests/$tag" 2>/dev/null)" ||
  stop "registry is unreachable; check ghcr.io availability and retry"
unset registry_response registry_reply registry_token
check_registry_status "$status"
for secret in harness-api-db harness-api-oidc; do
  kubectl -n "$APPS_NAMESPACE" get secret "$secret" >/dev/null 2>&1 || stop "required application secret missing; run install/66-harness-api-setup.sh"
done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/apps"
for file in deploy/apps/harness-api/*.yaml; do
  render "$file" "$tmp/apps/$(basename "$file")"
  sed -i "s/\${IMAGE_TAG}/$tag/g" "$tmp/apps/$(basename "$file")"
done
config_hash="$(sha256sum "$tmp/apps/configmap.yaml")"
config_hash="${config_hash%% *}"
[[ "$config_hash" =~ ^[a-f0-9]{64}$ ]] || stop "configuration hash could not be made; check sha256sum and retry"
sed -i "s/\${CONFIG_HASH}/$config_hash/g" "$tmp/apps/deployment.yaml"
kubectl apply -f "$tmp/apps/configmap.yaml" -f "$tmp/apps/service.yaml" -f "$tmp/apps/deployment.yaml"
printf 'Waiting for migrations and the new Harness API pod revision (%s)\n' "$tag"
kubectl -n "$APPS_NAMESPACE" rollout status deployment/harness-api --timeout=600s ||
  stop "new Harness API revision is not Ready; inspect the migrate container logs and image visibility"
resources="$(kubectl -n "$APPS_NAMESPACE" get deployment,replicaset,pod -l app=harness-api -o json)"
jq -e --arg image "$image" '
  ([.items[] | select(.kind == "Deployment" and .metadata.name == "harness-api")][0]) as $d |
  ($d.metadata.annotations["deployment.kubernetes.io/revision"]) as $revision |
  [.items[] | select(.kind == "ReplicaSet" and .metadata.annotations["deployment.kubernetes.io/revision"] == $revision)
    | select(any(.metadata.ownerReferences[]?; .uid == $d.metadata.uid)) | .metadata.uid] as $rs |
  $d.status.observedGeneration == $d.metadata.generation and
  $d.status.updatedReplicas == 1 and $d.status.readyReplicas == 1 and
  any(.items[]; .kind == "Pod" and .metadata.deletionTimestamp == null and
    any(.metadata.ownerReferences[]?; .uid as $uid | $rs | index($uid) != null) and
    any(.status.conditions[]?; .type == "Ready" and .status == "True") and
    any(.status.initContainerStatuses[]?; .name == "migrate" and .state.terminated.exitCode == 0) and
    any(.spec.containers[]; .name == "harness-api" and .image == $image))
' <<< "$resources" >/dev/null || stop "current revision or migrations could not be verified; inspect the deployment and pods"
kubectl -n "$APPS_NAMESPACE" delete configmap/harness-api --ignore-not-found
printf 'Running image: %s\nDONE\n' "$image"
