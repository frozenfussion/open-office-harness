#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Consumers deployment failed; inspect migration logs and pod readiness, then re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE; do
  [[ -n "${!variable:-}" && "${!variable}" != *[!a-zA-Z0-9.-]* ]] || stop "invalid deployment value $variable; correct deploy/values/$OOH_TARGET.env"
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
[[ $# == 1 ]] || stop "usage: install/75-consumers-deploy.sh <12-character-image-tag>"
for tool in kubectl curl jq git sed mktemp sha256sum; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
tag="$1"
[[ "$tag" =~ ^[a-f0-9]{12}$ ]] || stop "image tag must be the first 12 characters of the image commit hash"
check_registry_status() {
  case "$1" in
    200) ;;
    404) stop "image not built yet; run the workflow for this commit" ;;
    401|403) stop "image not found or not public; check that the workflow run for this commit is green, then switch the ooh-$name package to Public (service README)" ;;
    *) stop "registry check failed with HTTP $1; check ghcr.io availability and retry" ;;
  esac
}
for name in audit-writer cost-meter safety-watcher; do
  image="ghcr.io/frozenfussion/ooh-$name:$tag"
# A public registry token is anonymous and is supplied to curl on stdin.
registry_response="$(curl --connect-timeout 10 --max-time 30 -sS -w '\n%{http_code}' "https://ghcr.io/token?service=ghcr.io&scope=repository:frozenfussion/ooh-$name:pull" 2>/dev/null)" ||
  stop "registry is unreachable; check ghcr.io availability and retry"
check_registry_status "${registry_response##*$'\n'}"
registry_reply="${registry_response%$'\n'*}"
registry_token="$(printf '%s' "$registry_reply" | jq -er '.token // .access_token')"
[[ "$registry_token" =~ ^[a-zA-Z0-9._~+/-]+=*$ ]] || stop "registry returned an invalid token; retry the image check"
status="$(printf 'header = "Authorization: Bearer %s"\n' "$registry_token" |
  curl --config - --connect-timeout 10 --max-time 30 -sS -o /dev/null -w '%{http_code}' \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/frozenfussion/ooh-$name/manifests/$tag" 2>/dev/null)" ||
  stop "registry is unreachable; check ghcr.io availability and retry"
unset registry_response registry_reply registry_token
check_registry_status "$status"
  secrets=("$name-kafka")
  if [[ "$name" == safety-watcher ]]; then secrets+=("$name-oidc"); else secrets+=("$name-db"); fi
  for secret in "${secrets[@]}"; do
    kubectl -n "$APPS_NAMESPACE" get secret "$secret" >/dev/null 2>&1 || stop "required application secret missing; run install/74-consumers-setup.sh"
  done
done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"; ooh_target_cleanup' EXIT
for name in audit-writer cost-meter safety-watcher; do
  image="ghcr.io/frozenfussion/ooh-$name:$tag"
  mkdir -p "$tmp/$name"
  for file in "deploy/apps/$name/"*.yaml; do
    target="$tmp/$name/$(basename "$file")"
    render "$file" "$target"
    sed -i "s/\${IMAGE_TAG}/$tag/g" "$target"
  done
  config_hash="$(sha256sum "$tmp/$name/configmap.yaml")"
  config_hash="${config_hash%% *}"
  sed -i "s/\${CONFIG_HASH}/$config_hash/g" "$tmp/$name/deployment.yaml"
  kubectl apply -f "$tmp/$name/configmap.yaml" -f "$tmp/$name/service.yaml" -f "$tmp/$name/deployment.yaml"
  kubectl -n "$APPS_NAMESPACE" rollout status "deployment/$name" --timeout=600s || stop "$name not Ready; inspect its pod and migration logs"
  resources="$(kubectl -n "$APPS_NAMESPACE" get deployment,replicaset,pod -l "app=$name" -o json)"
  jq -e --arg image "$image" --arg app "$name" '
    ([.items[] | select(.kind == "Deployment" and .metadata.name == $app)][0]) as $d |
    ($d.metadata.annotations["deployment.kubernetes.io/revision"]) as $revision |
    [.items[] | select(.kind == "ReplicaSet" and .metadata.annotations["deployment.kubernetes.io/revision"] == $revision)
      | select(any(.metadata.ownerReferences[]?; .uid == $d.metadata.uid)) | .metadata.uid] as $rs |
    $d.status.observedGeneration == $d.metadata.generation and
    $d.status.updatedReplicas == 1 and $d.status.readyReplicas == 1 and
    any(.items[]; .kind == "Pod" and .metadata.deletionTimestamp == null and
      any(.metadata.ownerReferences[]?; .uid as $uid | $rs | index($uid) != null) and
      any(.status.conditions[]?; .type == "Ready" and .status == "True") and
      ($app == "safety-watcher" or any(.status.initContainerStatuses[]?; .name == "migrate" and .state.terminated.exitCode == 0)) and
      any(.spec.containers[]; .name == $app and .image == $image))
  ' <<< "$resources" >/dev/null || stop "$name current revision or migrations could not be verified"
  printf 'Running image: %s\n' "$image"
done
printf 'DONE\n'
