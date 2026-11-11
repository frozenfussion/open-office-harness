#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Slides worker deployment failed; inspect pod readiness, then re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$ROOT/install/lib/stage-check.sh" ]] || stop "stage-check helper missing; use the merged Stage 3 worktree"
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
[[ $# -le 1 ]] || stop "usage: install/73-slides-worker-deploy.sh [12-character-image-tag]"
for tool in kubectl curl jq git sed mktemp sha256sum; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
tag="${1:-$(git rev-parse --short=12 HEAD)}"
[[ "$tag" =~ ^[a-f0-9]{12}$ ]] || stop "image tag must be the first 12 characters of the image commit hash"
image="ghcr.io/frozenfussion/ooh-slides-worker:$tag"
check_registry_status() {
  case "$1" in
    200) ;;
    404) stop "image not built yet; run the workflow for this commit" ;;
    401|403) stop "image not found or not public; check that the workflow run for this commit is green, then switch the ooh-slides-worker package to Public (see services/slides-worker/README.md)" ;;
    *) stop "registry check failed with HTTP $1; check ghcr.io availability and retry" ;;
  esac
}
# A public registry token is anonymous and is supplied to curl on stdin.
registry_response="$(curl --connect-timeout 10 --max-time 30 -sS -w '\n%{http_code}' 'https://ghcr.io/token?service=ghcr.io&scope=repository:frozenfussion/ooh-slides-worker:pull' 2>/dev/null)" ||
  stop "registry is unreachable; check ghcr.io availability and retry"
check_registry_status "${registry_response##*$'\n'}"
registry_reply="${registry_response%$'\n'*}"
registry_token="$(printf '%s' "$registry_reply" | jq -er '.token // .access_token')"
[[ "$registry_token" =~ ^[a-zA-Z0-9._~+/-]+=*$ ]] || stop "registry returned an invalid token; retry the image check"
status="$(printf 'header = "Authorization: Bearer %s"\n' "$registry_token" |
  curl --config - --connect-timeout 10 --max-time 30 -sS -o /dev/null -w '%{http_code}' \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/frozenfussion/ooh-slides-worker/manifests/$tag" 2>/dev/null)" ||
  stop "registry is unreachable; check ghcr.io availability and retry"
unset registry_response registry_reply registry_token
check_registry_status "$status"
for secret in slides-worker-oidc slides-worker-kafka; do
  kubectl -n "$APPS_NAMESPACE" get secret "$secret" >/dev/null 2>&1 || stop "required application secret missing; run install/72-slides-worker-setup.sh"
done
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/apps"
for file in deploy/apps/slides-worker/*.yaml; do
  render "$file" "$tmp/apps/$(basename "$file")"
  sed -i "s/\${IMAGE_TAG}/$tag/g" "$tmp/apps/$(basename "$file")"
done
config_hash="$(sha256sum "$tmp/apps/configmap.yaml")"
config_hash="${config_hash%% *}"
[[ "$config_hash" =~ ^[a-f0-9]{64}$ ]] || stop "configuration hash could not be made; check sha256sum and retry"
sed -i "s/\${CONFIG_HASH}/$config_hash/g" "$tmp/apps/deployment.yaml"
kubectl apply -f "$tmp/apps/configmap.yaml" -f "$tmp/apps/service.yaml" -f "$tmp/apps/deployment.yaml"
printf 'Waiting for the new Slides worker pod revision (%s)\n' "$tag"
kubectl -n "$APPS_NAMESPACE" rollout status deployment/slides-worker --timeout=7500s ||
  stop "new Slides worker revision is not Ready; inspect the pod logs and image visibility"
resources="$(kubectl -n "$APPS_NAMESPACE" get deployment,replicaset,pod -l app=slides-worker -o json)"
jq -e --arg image "$image" '
  ([.items[] | select(.kind == "Deployment" and .metadata.name == "slides-worker")][0]) as $d |
  ($d.metadata.annotations["deployment.kubernetes.io/revision"]) as $revision |
  [.items[] | select(.kind == "ReplicaSet" and .metadata.annotations["deployment.kubernetes.io/revision"] == $revision)
    | select(any(.metadata.ownerReferences[]?; .uid == $d.metadata.uid)) | .metadata.uid] as $rs |
  $d.status.observedGeneration == $d.metadata.generation and
  $d.status.updatedReplicas == 1 and $d.status.readyReplicas == 1 and
  any(.items[]; .kind == "Pod" and .metadata.deletionTimestamp == null and
    any(.metadata.ownerReferences[]?; .uid as $uid | $rs | index($uid) != null) and
    any(.status.conditions[]?; .type == "Ready" and .status == "True") and
    any(.spec.containers[]; .name == "slides-worker" and .image == $image))
' <<< "$resources" >/dev/null || stop "current revision could not be verified; inspect the deployment and pods"
printf 'Running image: %s\n' "$image"
# shellcheck source=install/lib/stage-check.sh
source "$ROOT/install/lib/stage-check.sh"
check_active=0
cleanup() {
  local status=$?
  trap - EXIT
  if ((check_active)); then stage_check_end || status=1; fi
  rm -rf -- "$tmp"
  exit "$status"
}
trap cleanup EXIT
stage_check_begin || stop "could not start the stage check; inspect the STOP line above"
check_active=1
access_token="$(stage_check_token ooh-control-centre)" || stop "could not obtain a stage-check token"
api="https://admin.$DOMAIN/api/admin/skills"
request() {
  local method="$1" url="$2"
  shift 2
  printf 'header = "Authorization: Bearer %s"\n' "$access_token" |
    curl --config - --connect-timeout 10 --max-time 30 -sS -o "$tmp/manifest-response" -w '%{http_code}' \
      -X "$method" "$url" "$@" 2>/dev/null
}
status="$(request GET "$api/slides")" || stop "could not read the Slides manifest; check Control Centre readiness"
case "$status" in
  404) method=POST; url="$api" ;;
  200)
    if jq -e --slurpfile manifest "$ROOT/contracts/skills/slides/manifest.json" '. == $manifest[0]' "$tmp/manifest-response" >/dev/null; then
      method=''
    else method=PUT; url="$api/slides"; fi ;;
  *) stop "Slides manifest read failed with HTTP $status; inspect Control Centre readiness" ;;
esac
if [[ -n "$method" ]]; then
  status="$(request "$method" "$url" -H 'Content-Type: application/json' --data-binary "@$ROOT/contracts/skills/slides/manifest.json")" || stop "could not save the Slides manifest; retry this script"
  [[ "$status" == 200 || "$status" == 201 ]] || stop "Slides manifest save failed with HTTP $status; inspect Control Centre readiness"
fi
unset access_token
stage_check_end || stop "stage-check client could not be disabled; inspect Keycloak and re-run this script"
check_active=0
printf 'Slides manifest registered\nDONE\n'
