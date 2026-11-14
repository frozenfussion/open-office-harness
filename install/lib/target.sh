#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Sourced by platform and application scripts; only the creating shell owns cleanup.
OOH_TARGET=${OOH_TARGET:-do}
case "$OOH_TARGET" in
  do|aws) ;;
  *) stop 'OOH_TARGET must be do or aws' ;;
esac
if [[ -n "${OOH_FROZEN_TARGET:-}" || -n "${OOH_FROZEN_KUBECONFIG:-}" ]]; then
  [[ "${OOH_FROZEN_TARGET:-}" == "$OOH_TARGET" ]] || stop 'child script target differs from its parent'
  [[ -n "${OOH_FROZEN_KUBECONFIG:-}" && -f "$OOH_FROZEN_KUBECONFIG" ]] || stop 'frozen kubeconfig is missing; retry the parent script'
fi
# shellcheck source=/dev/null
source "$ROOT/deploy/values/$OOH_TARGET.env"
export OOH_TARGET
OOH_LOCAL="$HOME/.config/ooh"
if [[ "$OOH_TARGET" == "do" ]]; then
  printf 'TARGET do (Droplet, live class system)\n'
else
  printf 'TARGET aws (EKS copy)\n'
  OOH_LOCAL="$HOME/.config/ooh/aws"
fi
export OOH_LOCAL
if [[ -n "${OOH_FROZEN_KUBECONFIG:-}" ]]; then
  KUBECONFIG=$OOH_FROZEN_KUBECONFIG
else
  # shellcheck disable=SC2153 # KUBE_CONFIG is set in the selected values file.
  KUBECONFIG=$KUBE_CONFIG
fi
export KUBECONFIG
OOH_TARGET_OWNER_PID=''
OOH_TARGET_PRIVATE_CONFIG=''
ooh_target_cleanup() {
  if [[ "$OOH_TARGET_OWNER_PID" == "$BASHPID" && -n "$OOH_TARGET_PRIVATE_CONFIG" ]]; then
    rm -f -- "$OOH_TARGET_PRIVATE_CONFIG"
    OOH_TARGET_PRIVATE_CONFIG=''
  fi
}
trap ooh_target_cleanup EXIT
# Only 30's exact render-only invocation may bypass cluster identity checks.
ooh_caller=${BASH_SOURCE[1]:-}
if [[ "${ooh_caller##*/}" == 30-platform-apply.sh && $# == 1 && "$1" == --check ]]; then
  return 0
fi
for ooh_tool in kubectl jq mktemp; do
  command -v "$ooh_tool" >/dev/null || stop "missing tool $ooh_tool; finish server setup"
done
if [[ "$OOH_TARGET" == aws ]]; then
  [[ -f "$HOME/.config/ooh/aws.env" ]] || stop 'AWS local settings missing; run install/82-aws-cluster.sh'
  ooh_settings="$(
    # Do not import account, budget or sign-in settings into deployment scripts.
    # shellcheck source=/dev/null
    source "$HOME/.config/ooh/aws.env"
    printf '%s\n%s\n%s\n' "${EKS_ENDPOINT:-}" "${EKS_CLUSTER_NAME:-}" "${LB_HOSTNAME:-}"
  )" || stop 'cannot read AWS local settings; run install/82-aws-cluster.sh'
  mapfile -t ooh_settings_rows <<< "$ooh_settings"
  EKS_ENDPOINT=${ooh_settings_rows[0]:-}
  EKS_CLUSTER_NAME=${ooh_settings_rows[1]:-}
  LB_HOSTNAME=${ooh_settings_rows[2]:-}
  [[ "$EKS_ENDPOINT" == https://* ]] || stop 'AWS endpoint missing; run install/82-aws-cluster.sh'
  ooh_expected_server=$EKS_ENDPOINT
  ooh_provider_prefix='aws:///ap-southeast-1a/'
else
  ooh_expected_server=https://127.0.0.1:6443
  ooh_provider_prefix=k3s://
fi
if [[ -z "${OOH_FROZEN_KUBECONFIG:-}" ]]; then
  OOH_TARGET_OWNER_PID=$BASHPID
  OOH_TARGET_PRIVATE_CONFIG="$(mktemp "${TMPDIR:-/tmp}/ooh-kubeconfig.XXXXXXXX")"
  chmod 600 "$OOH_TARGET_PRIVATE_CONFIG"
  # Snapshot before checking, so even a simultaneous context switch cannot redirect checks.
  kubectl config view --minify --flatten > "$OOH_TARGET_PRIVATE_CONFIG" || stop 'cannot read kubeconfig; check target settings'
  KUBECONFIG=$OOH_TARGET_PRIVATE_CONFIG
  export KUBECONFIG
fi
ooh_found_server="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')" || stop 'cannot read cluster endpoint; check target settings'
[[ "$ooh_found_server" == "$ooh_expected_server" ]] || stop "this shell points at $ooh_found_server, not the $OOH_TARGET cluster; nothing was changed"
ooh_nodes="$(kubectl --request-timeout=15s get nodes -o json)" || stop "cannot read nodes in the $OOH_TARGET cluster; check access and retry"
jq -e '.items | length > 0' <<< "$ooh_nodes" >/dev/null || stop "no node is registered yet in the $OOH_TARGET cluster; wait and retry"
jq -e --arg prefix "$ooh_provider_prefix" 'any(.items[]; (.spec.providerID // "") | startswith($prefix))' <<< "$ooh_nodes" >/dev/null || stop "this shell points at $ooh_found_server with an unexpected node provider, not the $OOH_TARGET cluster; nothing was changed"
OOH_FROZEN_KUBECONFIG=$KUBECONFIG
OOH_FROZEN_TARGET=$OOH_TARGET
export OOH_FROZEN_KUBECONFIG OOH_FROZEN_TARGET
