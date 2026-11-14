#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Stage 2 check could not continue; check readiness and the last FAIL line, then retry"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
[[ $# == 0 ]] || stop "usage: install/70-check-stage-2.sh"
for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE; do
  [[ -n "${!variable:-}" && "${!variable}" != *[!a-zA-Z0-9.-]* ]] || stop "invalid deployment value $variable; correct deploy/values/$OOH_TARGET.env"
done
for tool in kubectl curl jq date mktemp openssl tr; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
failed=0
result() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s: %s\n' "$2" "$3"; failed=1; fi
}
require() {
  result "$1" "$2" "$3"
  [[ "$1" == 0 ]] || stop "cannot continue after $2; fix the FAIL line and re-run"
}
tmp="$(mktemp -d)"
config_dir=''
check_pod=''
forward_pids=()
cleanup() {
  local pid
  for pid in "${forward_pids[@]}"; do kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; done
  if [[ -n "$check_pod" ]]; then kubectl -n "$PLATFORM_NAMESPACE" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; fi
  if [[ "$config_dir" =~ ^/tmp/ooh-stage-check\.[a-zA-Z0-9]+$ ]]; then
    kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- rm -rf -- "$config_dir" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$tmp"
}
trap 'cleanup; ooh_target_cleanup' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
forward() {
  local port="$1" service="$2" target="$3" pid ready=false output
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    stop "local port $port is busy; stop the old port-forward (pkill -f \"port-forward.*$port\") and re-run"
  fi
  # Create the log synchronously before the child can race the readiness read.
  : >"$tmp/forward-$port.log" || stop "port-forward for $service could not start; check service readiness and local port $port"
  kubectl -n "$APPS_NAMESPACE" port-forward --address 127.0.0.1 "service/$service" "$port:$target" >"$tmp/forward-$port.log" 2>&1 &
  pid=$!
  forward_pids+=("$pid")
  for ((attempt=0; attempt<30; attempt++)); do
    kill -0 "$pid" 2>/dev/null || break
    output="$(<"$tmp/forward-$port.log")" ||
      stop "port-forward for $service could not start; check service readiness and local port $port"
    if [[ "$output" == *"Forwarding from 127.0.0.1:$port"* ]]; then ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true ]] || stop "port-forward for $service could not start; check service readiness and local port $port"
}
forward 18080 model-gateway 8080
forward 18081 control-centre 8081
issuer="https://auth.$DOMAIN/realms/ooh"
form_encode() { jq -sRr @uri; }
token_request() {
  curl --connect-timeout 10 --max-time 30 -sS -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-binary @- "$issuer/protocol/openid-connect/token" 2>/dev/null
}
service_token() {
  local client="$1" secret reply token
  case "$client" in
    ooh-harness-api) secret="$harness_secret" ;;
    ooh-model-gateway) secret="$gateway_secret" ;;
    ooh-control-centre) secret="$centre_secret" ;;
    *) return 1 ;;
  esac
  if ! reply="$(printf 'grant_type=client_credentials&client_id=%s&client_secret=%s' "$client" "$secret" | token_request)"; then
    printf 'FAIL service token for %s: Keycloak token endpoint could not be reached\n' "$client" >&2
    return 1
  fi
  if ! token="$(printf '%s' "$reply" | jq -jer '.access_token | select(type == "string" and length > 0)' 2>/dev/null)"; then
    if printf '%s' "$reply" | jq -e '.error == "invalid_client" or .error == "unauthorized_client"' >/dev/null 2>&1; then
      printf 'FAIL service token for %s: Keycloak refused the client credentials\n' "$client" >&2
    else
      printf 'FAIL service token for %s: Keycloak did not return a valid access token\n' "$client" >&2
    fi
    return 1
  fi
  printf '%s' "$token"
}
config_dir="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- /bin/bash -c 'umask 077; mktemp -d /tmp/ooh-stage-check.XXXXXXXX')"
[[ "$config_dir" =~ ^/tmp/ooh-stage-check\.[a-zA-Z0-9]+$ ]] || stop "could not create private Keycloak CLI settings directory"
# shellcheck disable=SC2016 # Credentials are expanded only inside the Keycloak pod.
kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- sh -c '
  set -eu
  set +x
  umask 077
  /opt/keycloak/bin/kcadm.sh config credentials --config "$1" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  chmod 600 "$1"
' -- "$config_dir/kcadm.config" 2>/dev/null || stop "Keycloak CLI login failed; check bootstrap access privately"
read_client_secret() {
  local client="$1" reply
  # Capture the client secret inside the pod before transferring it privately to this shell.
  # shellcheck disable=SC2016 # Pod-local expansion, not host expansion.
  reply="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- sh -c '
    set -eu
    set +x
    clients="$(/opt/keycloak/bin/kcadm.sh get clients -r ooh -q "clientId=$2" --fields id --format csv --noquotes --config "$1" 2>/dev/null)"
    case "$clients" in ""|*[!a-fA-F0-9-]*) exit 1;; esac
    secret="$(/opt/keycloak/bin/kcadm.sh get "clients/$clients/client-secret" -r ooh --config "$1" 2>/dev/null)"
    printf "%s" "$secret"
  ' -- "$config_dir/kcadm.config" "$client" 2>/dev/null)" || return 1
  printf '%s' "$reply" | jq -jer '.value | select(type == "string" and length > 0)' | form_encode
}
harness_secret="$(read_client_secret ooh-harness-api)" || stop "Harness client secret unavailable; inspect the existing Keycloak client privately"
gateway_secret="$(read_client_secret ooh-model-gateway)" || stop "Gateway client secret unavailable; inspect the existing Keycloak client privately"
centre_secret="$(read_client_secret ooh-control-centre)" || stop "Control Centre client secret unavailable; inspect the existing Keycloak client privately"
request() {
  local principal="$1" method="$2" url="$3" data="${4:-}" token='' reply
  status=''; body=''
  if [[ "$principal" != anonymous ]]; then
    token="$(service_token "$principal")" || stop "service token unavailable; inspect Keycloak privately and retry"
    [[ "$token" =~ ^[A-Za-z0-9_.-]+$ ]] || stop "invalid service token; inspect Keycloak privately"
  fi
  reply="$(
    {
      [[ -z "$token" ]] || printf 'header = "Authorization: Bearer %s"\n' "$token"
      printf 'header = "Content-Type: application/json"\n'
      if [[ -n "$data" ]]; then printf 'data = '; jq -Rs . <<< "$data"; fi
    } | curl --config - --connect-timeout 10 --max-time 950 -sS -X "$method" "$url" -w '\n%{http_code}' 2>/dev/null
  )" || return 1
  status="${reply##*$'\n'}"
  body="${reply%$'\n'*}"
}
registration_verifier="$(openssl rand -hex 32)"
registration_challenge="$(printf '%s' "$registration_verifier" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
registration_query="$(jq -rn --arg redirect "https://harness.$DOMAIN/" --arg challenge "$registration_challenge" '
  {client_id:"ooh-workspace",redirect_uri:$redirect,response_type:"code",scope:"openid profile",prompt:"create",code_challenge:$challenge,code_challenge_method:"S256",ui_locales:"en"} |
  to_entries | map(.key + "=" + (.value | @uri)) | join("&")')"
rc=0
registration_reply="$(curl --connect-timeout 10 --max-time 30 -sS -L -w '\n%{http_code}' \
  "$issuer/protocol/openid-connect/auth?$registration_query" 2>/dev/null)" || rc=1
registration_status="${registration_reply##*$'\n'}"
registration_page="${registration_reply%$'\n'*}"
[[ "$registration_status" == 200 && "$registration_page" == *'id="kc-register-form"'* && "$registration_page" == *'Request access'* &&
   "$registration_page" == *'name="organisation"'* && "$registration_page" == *'name="access_reason"'* ]] || rc=1
result "$rc" 'Workspace prompt=create registration page' 'expected HTTP 200, kc-register-form, Request access and both extra fields; check realm sync and whether registration is switched off'
unset registration_verifier registration_challenge registration_reply registration_page
rc=0
request ooh-harness-api POST "https://admin.$DOMAIN/api/access/observe" \
  '{"user_id":"stage-check-access","name":null,"email":null,"organisation":null,"access_reason":null,"is_admin":false}' && [[ "$status" == 200 ]] &&
  jq -e '.status == "pending" or .status == "rejected" or .status == "closed"' <<< "$body" >/dev/null || rc=1
result "$rc" 'access check user is not approved' 'expected pending, rejected or closed; inspect the Control Centre observe route and reserved stage-check-access row'
for app in workspace admin-console; do
  host=harness
  [[ "$app" != admin-console ]] || host="admin"
  rc=0
  request anonymous GET "https://$host.$DOMAIN/" && [[ "$status" == 200 && "$body" == *'<app-root'* ]] || rc=1
  result "$rc" "$app page" 'expected HTTP 200 and app-root; check deployment, ingress and TLS'
  rc=0
  request anonymous GET "https://$host.$DOMAIN/config.json" && [[ "$status" == 200 ]] &&
    jq -e --arg client "ooh-$app" --arg issuer "$issuer" '.clientId == $client and .issuer == $issuer and .apiBase == "/api"' <<< "$body" >/dev/null || rc=1
  result "$rc" "$app settings" 'check its ConfigMap and config.json mount'
done
for principal in anonymous ooh-control-centre; do
  rc=0
  request "$principal" GET "https://harness.$DOMAIN/api/conversations" && [[ "$status" == 401 ]] || rc=1
  result "$rc" "Harness refuses $principal" 'expected HTTP 401; check user-token audience validation'
done
rc=0
ingresses="$(kubectl get ingress --all-namespaces -o json)" || rc=1
jq -e 'all(.items[]; (.spec.defaultBackend.service.name != "model-gateway") and all(.spec.rules[]?.http.paths[]?; .backend.service.name != "model-gateway"))' <<< "$ingresses" >/dev/null || rc=1
result "$rc" 'Gateway has no public ingress' 'remove any Gateway ingress before using provider keys'
payload='{"purpose":"chat","tier":98,"user_id":"admin-test-stage-check-'"$(cat /proc/sys/kernel/random/uuid)"'","messages":[{"role":"user","content":"Reply with the single word OK."}],"stream":false}'
rc=0
request ooh-control-centre POST http://127.0.0.1:18080/v1/call "$payload" && [[ "$status" == 403 ]] &&
  jq -e '.code == "forbidden"' <<< "$body" >/dev/null || rc=1
result "$rc" 'Gateway refuses unpinned Control Centre call' 'expected HTTP 403 forbidden; check the Control Centre test-call restriction'
payload="$(jq -c --arg user "stage-check-$(cat /proc/sys/kernel/random/uuid)" '.user_id = $user' <<< "$payload")"
rc=0
request ooh-harness-api POST http://127.0.0.1:18080/v1/call "$payload" && [[ "$status" == 404 ]] &&
  jq -e '.code == "no_model"' <<< "$body" >/dev/null || rc=1
result "$rc" 'Gateway reports no model for tier 98' 'keep tier 98 empty; check registry access and no_model response'
entries='[]'
for ((tier=1; tier<=20; tier++)); do
  rc=0
  request ooh-model-gateway GET "http://127.0.0.1:18081/api/models?purpose=chat&tier=$tier" && [[ "$status" == 200 ]] &&
    jq -e 'type == "array"' <<< "$body" >/dev/null || rc=1
  require "$rc" "read chat tier $tier" 'expected registry array on internal port 8081; check Gateway token and Control Centre'
  entries="$(printf '%s\n%s\n' "$entries" "$body" | jq -cs '.[0] + [.[1][] | select(.has_key == true and .deleted_at == null)] | unique_by(.model_entry_id)')"
done
call_users='[]'
centre_entry="$(jq -c 'first // null' <<< "$entries")"
centre_id="$(jq -r '.model_entry_id // empty' <<< "$centre_entry")"
centre_tier="$(jq -r '.tier // 98' <<< "$centre_entry")"
# A valid but absent ID still lets the caller rules be checked when no key is saved.
centre_pin="${centre_id:-$(cat /proc/sys/kernel/random/uuid)}"
centre_user="admin-test-stage-check-$(cat /proc/sys/kernel/random/uuid)"
centre_payload="$(jq -cn --arg id "$centre_pin" --arg user "$centre_user" --argjson tier "$centre_tier" \
  '{purpose:"chat",tier:$tier,user_id:$user,model_entry_id:$id,messages:[{role:"user",content:"Reply with the single word OK."}],stream:false}')"
for refusal in streamed other-messages; do
  if [[ "$refusal" == streamed ]]; then
    refused_payload="$(jq -c '.stream = true' <<< "$centre_payload")"
  else
    refused_payload="$(jq -c '.messages = [{role:"user",content:"Reply with a different word."}]' <<< "$centre_payload")"
  fi
  rc=0
  request ooh-control-centre POST http://127.0.0.1:18080/v1/call "$refused_payload" && [[ "$status" == 403 ]] &&
    jq -e '.code == "forbidden"' <<< "$body" >/dev/null || rc=1
  result "$rc" "Gateway refuses $refusal Control Centre call" 'expected HTTP 403 forbidden; check the Control Centre test-call restriction'
done
if [[ -n "$centre_id" ]]; then
  call_users="$(jq -c --arg user "$centre_user" '. + [$user]' <<< "$call_users")"
  rc=0
  request ooh-control-centre POST http://127.0.0.1:18080/v1/call "$centre_payload" && [[ "$status" == 200 ]] &&
    jq -e --arg id "$centre_id" '.model_entry_id == $id and (.content | type == "string" and length > 0)' <<< "$body" >/dev/null || rc=1
  result "$rc" 'Control Centre pinned test call' 'expected HTTP 200 and nonempty content; check realm sync, the saved key, rate limit and daily budget privately'
else
  printf 'NOTE Control Centre pinned test call skipped: no keyed chat entry in tiers 1 to 20\n'
fi
[[ "$(jq length <<< "$entries")" != 0 ]] || stop "no chat entry with a saved key in tiers 1 to 20; add models in the Admin Console first"
call_entry() {
  local entry="$1" stream="$2" id title tier payload user rc=0
  local prompt='Reply with the single word OK.' events reason delta_count thinking_count last_event http_status
  local budget_exceeded=false
  [[ "$stream" != true ]] || prompt='Count from 1 to 20, separated by spaces.'
  id="$(jq -er '.model_entry_id' <<< "$entry")"
  title="$(jq -r '.title' <<< "$entry")"
  tier="$(jq -er '.tier' <<< "$entry")"
  user="stage-check-$(cat /proc/sys/kernel/random/uuid)"
  call_users="$(jq -c --arg user "$user" '. + [$user]' <<< "$call_users")"
  payload="$(jq -cn --arg id "$id" --arg user "$user" --arg prompt "$prompt" --argjson tier "$tier" --argjson stream "$stream" \
    '{purpose:"chat",tier:$tier,user_id:$user,model_entry_id:$id,messages:[{role:"user",content:$prompt}],stream:$stream}')"
  request ooh-harness-api POST http://127.0.0.1:18080/v1/call "$payload" || rc=1
  if [[ "$status" == 503 ]] && jq -e '.code == "budget_exceeded"' <<< "$body" >/dev/null 2>&1; then
    if [[ "$stream" == false ]]; then
      result 1 "$title" 'over its daily budget today'
      return
    fi
    budget_exceeded=true
  fi
  [[ "$status" == 200 ]] || rc=1
  if [[ "$stream" == false ]]; then
    jq -e --arg title "$title" --arg id "$id" '
      (.content | type == "string" and length > 0) and .model_entry_id == $id and .model_title == $title and
      (.usage.input_tokens + .usage.output_tokens > 0)' <<< "$body" >/dev/null 2>&1 || rc=1
    result "$rc" "$title non-streamed answer" 'expected pinned entry, title, nonempty text and usage; check connection settings privately'
  else
    events="$(while IFS= read -r line; do
      line="${line%$'\r'}"
      [[ "$line" != 'data:'* ]] || printf '%s\n' "${line#data:}"
    done <<< "$body")"
    jq -se --arg id "$id" '
      ([.[] | select(.type == "delta")] | length >= 2) and
      last.type == "completed" and last.model_entry_id == $id and
      ([.[] | select(.type == "completed")] | length == 1) and
      all(.[0:-1][]; .type == "delta" or .type == "thinking")' <<< "$events" >/dev/null 2>&1 || rc=1
    reason='expected optional thinking, at least two deltas and one final completed; inspect stream buffering and provider settings'
    [[ "$budget_exceeded" != true ]] || reason='over its daily budget today'
    if [[ "$rc" != 0 ]]; then
      delta_count="$(jq -sr '[.[] | select(.type == "delta")] | length' <<< "$events" 2>/dev/null)" || delta_count=0
      thinking_count="$(jq -sr '[.[] | select(.type == "thinking")] | length' <<< "$events" 2>/dev/null)" || thinking_count=0
      last_event="$(jq -sr '
        if length == 0 then "none"
        elif (last.type == "thinking" or last.type == "delta" or last.type == "completed" or last.type == "failed" or last.type == "tool_call") then last.type
        else "unknown" end' <<< "$events" 2>/dev/null)" || last_event=invalid
      http_status="${status:-000}"
      [[ "$http_status" =~ ^[0-9]{3}$ ]] || http_status=000
      reason+=" ($delta_count deltas, $thinking_count thinking, last event $last_event, HTTP $http_status)"
    fi
    result "$rc" "$title streamed answer" "$reason"
  fi
}
while IFS= read -r entry; do call_entry "$entry" false; done < <(jq -c '.[]' <<< "$entries")
while IFS= read -r entry; do call_entry "$entry" true; done < <(jq -c 'group_by(.api_type) | .[] | first' <<< "$entries")

usage_rows() {
  local role_secret script phase='' deadline
  role_secret="$(kubectl -n "$PLATFORM_NAMESPACE" get databaseroles -o json |
    jq -er '[.items[] | select(.spec.name == "modelgateway_app")] | select(length == 1) | .[0].spec.passwordSecret.name')" || return 1
  # The password expands only inside the check pod, never into kubectl arguments.
  # shellcheck disable=SC2016
  script='set -euo pipefail
set +x
result="$(printf "SELECT count(*) = %s AND count(DISTINCT user_id) = %s FROM usage WHERE user_id IN (%s);\n" "$EXPECTED" "$EXPECTED" "$CALL_USERS" | psql -X -h ooh-pg-rw -U modelgateway_app -d modelgateway -At -v ON_ERROR_STOP=1 2>/dev/null)"
[[ "$result" == t ]]'
  check_pod="ooh-stage2-usage-$(date +%s)-$RANDOM"
  jq -n --arg name "$check_pod" --arg namespace "$PLATFORM_NAMESPACE" --arg script "$script" \
    --arg secret "$role_secret" --arg users "$(jq -r 'map("\u0027" + . + "\u0027") | join(",")' <<< "$call_users")" --arg expected "$(jq length <<< "$call_users")" '
    {apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:$namespace},spec:{restartPolicy:"Never",activeDeadlineSeconds:150,automountServiceAccountToken:false,
    securityContext:{runAsNonRoot:true,runAsUser:1001,runAsGroup:1001,fsGroup:1001,seccompProfile:{type:"RuntimeDefault"}},
    containers:[{name:"check",image:"ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie",command:["/bin/bash","-ec",$script],
    env:[{name:"PGPASSWORD",valueFrom:{secretKeyRef:{name:$secret,key:"password"}}},{name:"PGSSLMODE",value:"require"},{name:"CALL_USERS",value:$users},{name:"EXPECTED",value:$expected}],
    resources:{requests:{cpu:"100m",memory:"128Mi"},limits:{cpu:"500m",memory:"512Mi"}},
    securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"tmp",mountPath:"/tmp"}]}],
    volumes:[{name:"tmp",emptyDir:{medium:"Memory",sizeLimit:"16Mi"}}]}}' |
    kubectl create -f - >/dev/null || return 1
  deadline=$((SECONDS + 160))
  while ((SECONDS < deadline)); do
    phase="$(kubectl -n "$PLATFORM_NAMESPACE" get pod "$check_pod" -o jsonpath='{.status.phase}')" || break
    [[ "$phase" != Succeeded && "$phase" != Failed ]] || break
    sleep 2
  done
  kubectl -n "$PLATFORM_NAMESPACE" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null || return 1
  check_pod=''
  [[ "$phase" == Succeeded ]]
}
rc=0
usage_rows || rc=1
result "$rc" 'one usage row per pinned call' 'check modelgateway_app role, Secret and Gateway usage writes; each fresh check user must have exactly one row'

# Key responses and logs stay in shell variables. No key is printed or passed as an argument.
while IFS= read -r id; do
  rc=0
  request ooh-model-gateway GET "http://127.0.0.1:18081/api/models/$id/key" && [[ "$status" == 200 ]] || rc=1
  key="$(jq -jer '.api_key | select(type == "string" and length > 0)' <<< "$body")" || rc=1
  logs=''
  for deployment in control-centre model-gateway harness-api; do
    current_logs="$(kubectl -n "$APPS_NAMESPACE" logs -l "app=$deployment" --all-containers=true --since-time="$started" --tail=-1 --max-log-requests=10 2>/dev/null)" ||
      stop "could not read $deployment logs; inspect pod readiness and retry"
    logs+="$current_logs"
  done
  [[ -n "$key" && "$logs" != *"$key"* ]] || rc=1
  unset key body
  result "$rc" "key absent from logs for $id" 'expected saved key and no match in service logs; inspect privately and rotate a leaked key'
done < <(jq -r '.[].model_entry_id' <<< "$entries")
unset logs current_logs
id="$(jq -er 'first.model_entry_id' <<< "$entries")"
rc=0
request ooh-harness-api GET "http://127.0.0.1:18081/api/models/$id/key" && [[ "$status" == 403 ]] || rc=1
result "$rc" 'Harness cannot read a provider key' 'expected HTTP 403 on internal key route; check service caller restrictions'
rc=0
request ooh-model-gateway GET "https://admin.$DOMAIN/api/models/$id/key" && [[ "$status" == 404 ]] || rc=1
result "$rc" 'key route is not public' 'expected HTTP 404 on the public host; check Control Centre port routing'
((failed == 0)) || stop "Stage 2 checks failed; fix every FAIL line before repeating"
printf 'DONE\n'
