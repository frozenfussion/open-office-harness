#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Control Centre check could not continue; fix the last FAIL or check platform readiness and retry"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
for variable in DOMAIN PLATFORM_NAMESPACE APPS_NAMESPACE; do
  [[ -n "${!variable:-}" && "${!variable}" != *[!a-zA-Z0-9.-]* ]] || stop "invalid deployment value $variable; correct deploy/values/do.env"
done
[[ $# == 0 ]] || stop "usage: install/62-check-control-centre.sh"
for tool in kubectl jq curl date openssl tr; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
failed=0
correlation_id=""
audit_correlations=""
result() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s: %s\n' "$2" "$3"; failed=1; fi
}
require() {
  local rc="$1" label="$2" reason="$3"
  result "$rc" "$label" "$reason"
  [[ "$rc" == 0 ]] || stop "cannot continue after $label; fix the FAIL line and re-run"
}
if (exec 3<>/dev/tcp/127.0.0.1/18081) 2>/dev/null; then
  stop 'local port 18081 is busy; stop the old port-forward (pkill -f "port-forward.*18081") and re-run'
fi
issuer="https://auth.$DOMAIN/realms/ooh"
base="https://admin.$DOMAIN"
# shellcheck source=install/lib/stage-check.sh
source "$ROOT/install/lib/stage-check.sh"
config_dir=''
check_pod=''
forward_pid=''
forward_dir=''
cleanup() {
  stage_check_end || true;
  if [[ -n "$forward_pid" ]]; then kill "$forward_pid" 2>/dev/null || true; wait "$forward_pid" 2>/dev/null || true; fi
  if [[ -n "$forward_dir" ]]; then rm -rf -- "$forward_dir"; fi
  if [[ -n "$check_pod" ]]; then kubectl -n "$PLATFORM_NAMESPACE" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; fi
  if [[ "$config_dir" =~ ^/tmp/ooh-stage-check\.[a-zA-Z0-9]+$ ]]; then
    kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- rm -rf -- "$config_dir" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
forward_dir="$(mktemp -d)"
kubectl -n "$APPS_NAMESPACE" port-forward service/control-centre 18081:8081 >"$forward_dir/log" 2>&1 &
forward_pid=$!
for ((attempt=0; attempt<30; attempt++)); do
  if curl -s --max-time 1 http://127.0.0.1:18081/health >/dev/null; then break; fi
  kill -0 "$forward_pid" 2>/dev/null || stop "internal port-forward failed; check Control Centre readiness"
  sleep 1
done
curl -s --max-time 2 http://127.0.0.1:18081/health >/dev/null || stop "internal port-forward not ready; check Control Centre readiness"
form_encode() { jq -sRr @uri; }
token_request() {
  curl --connect-timeout 10 --max-time 30 -sS -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-binary @- "$issuer/protocol/openid-connect/token" 2>/dev/null
}
# Secrets and tokens reach curl only on stdin; no response bodies are displayed.
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
refresh_admin() { admin_token="$(stage_check_token ooh-control-centre)"; }
request() {
  local principal="$1" method="$2" path="$3" data="${4:-}" token='' reply
  case "$principal" in
    admin) refresh_admin || return 1; token="$admin_token" ;;
    anonymous) ;;
    *) token="$(service_token "$principal")" || stop "service token unavailable; fix the failure above and re-run" ;;
  esac
  [[ -z "$token" || "$token" =~ ^[A-Za-z0-9_.-]+$ ]] || return 1
  local request_base="$base"
  [[ "$path" != /api/models* ]] || request_base="http://127.0.0.1:18081"
  reply="$(
    {
      [[ -z "$token" ]] || printf 'header = "Authorization: Bearer %s"\n' "$token"
      printf 'header = "Content-Type: application/json"\n'
      if [[ -n "$data" ]]; then
        printf 'data = '
        printf '%s' "$data" | jq -Rs .
      fi
    } | curl --config - --connect-timeout 10 --max-time 30 -sS -X "$method" "$request_base$path" -w '\n%{http_code}' 2>/dev/null
  )" || return 1
  status="${reply##*$'\n'}"
  body="${reply%$'\n'*}"
}
rc=0
request anonymous GET '/api/rights/me?user_id=x' && [[ "$status" == 401 ]] || rc=1
require "$rc" 'unauthenticated request refused' 'expected HTTP 401; check API ingress and deployment'

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
rc=0
request ooh-control-centre GET '/api/rights/me?user_id=x' && [[ "$status" == 401 ]] || rc=1
require "$rc" 'wrong audience refused' 'expected HTTP 401; check audience mappers and token validation'
user_id="stage-check-$(cat /proc/sys/kernel/random/uuid)"
rights_payload="$(jq -cn --arg user "$user_id" '{user_id:$user,action:"chat.tier",target:"99"}')"
rc=0
request ooh-harness-api POST /api/rights/check "$rights_payload" && [[ "$status" == 200 ]] &&
  jq -e '.allowed == false and .decided_by == "no-grant"' <<< "$body" >/dev/null || rc=1
require "$rc" 'new user has no grants' 'expected allowed false and no-grant; inspect rights rules and existing everyone grants'
rc=0
request ooh-model-gateway GET '/api/models?purpose=classification' && [[ "$status" == 200 ]] &&
  jq -e 'type == "array"' <<< "$body" >/dev/null || rc=1
require "$rc" 'Gateway registry access' 'expected HTTP 200 and a list'
rc=0
request ooh-harness-api GET '/api/models?purpose=classification' && [[ "$status" == 403 ]] || rc=1
require "$rc" 'Harness registry access refused' 'expected HTTP 403'

stage_check_begin || stop "check client could not start"
admin_token="$(stage_check_token ooh-control-centre)" || stop "check token unavailable"
printf 'PASS temporary admin client ready\n'

kafka() (
  local mode="$1" event="${2:-}" script manifest phase='' output rc=0
  local audit_partitions='' decision_partitions=''
  if [[ "$mode" == start ]]; then
    audit_partitions="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkatopic audit-events -o jsonpath='{.spec.partitions}')" ||
      stop "KafkaTopic audit-events partition count could not be read; inspect the topic and retry"
    decision_partitions="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkatopic approvals-decided -o jsonpath='{.spec.partitions}')" ||
      stop "KafkaTopic approvals-decided partition count could not be read; inspect the topic and retry"
    [[ "$audit_partitions" =~ ^[1-9][0-9]*$ ]] || stop "KafkaTopic audit-events partition count is invalid; inspect spec.partitions and retry"
    [[ "$decision_partitions" =~ ^[1-9][0-9]*$ ]] || stop "KafkaTopic approvals-decided partition count is invalid; inspect spec.partitions and retry"
  fi
  trap 'if [[ -n "$check_pod" ]]; then kubectl -n "$PLATFORM_NAMESPACE" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; fi' EXIT
  # shellcheck disable=SC2016 # Password and event expansion happen only inside the check pod.
  script='set -euo pipefail
set +x
umask 077
printf "security.protocol=SASL_PLAINTEXT\nsasl.mechanism=SCRAM-SHA-512\nsasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username=\"ooh-stage-check\" password=\"%s\";\n" "$PASSWORD" > /tmp/client.properties
unset PASSWORD
cd /opt/kafka/bin
if [[ "$MODE" == start ]]; then
  for topic in audit.events approvals.decided; do
    if [[ "$topic" == audit.events ]]; then expected="$AUDIT_PARTITIONS"; else expected="$DECISION_PARTITIONS"; fi
    ./kafka-consumer-groups.sh --bootstrap-server ooh-kafka-kafka-bootstrap:9092 --group ooh-stage-check --topic "$topic" --reset-offsets --to-latest --execute --command-config /tmp/client.properties > /tmp/reset.log 2>&1
    count=0
    while read -r group topic_name partition offset extra; do
      if [[ "$group" == ooh-stage-check && "$topic_name" == "$topic" ]]; then
        [[ "$partition" =~ ^[0-9]+$ && "$offset" =~ ^[0-9]+$ && -z "$extra" ]] || exit 1
        count=$((count + 1))
      fi
    done < /tmp/reset.log
    [[ "$count" == "$expected" ]] || exit 1
  done
elif [[ "$MODE" == publish ]]; then
  printf "%s\t%s\n%s\t%s\n" "$CORRELATION" "$EVENT" "$CORRELATION" "$EVENT" |
    ./kafka-console-producer.sh --bootstrap-server ooh-kafka-kafka-bootstrap:9092 --topic approvals.requested --producer.config /tmp/client.properties --property parse.key=true --property key.separator=$'"'\t'"' > /tmp/produce.log 2>&1
else
  if [[ "$MODE" == decisions ]]; then topic=approvals.decided; else topic=audit.events; fi
  ./kafka-console-consumer.sh --bootstrap-server ooh-kafka-kafka-bootstrap:9092 --topic "$topic" --group ooh-stage-check --timeout-ms 15000 --consumer.config /tmp/client.properties --consumer-property enable.auto.commit=false --consumer-property auto.offset.reset=none --property print.key=true --property key.separator=$'"'\t'"' > /tmp/read.log 2>/tmp/consume.log || true
  while IFS=$'"'\t'"' read -r key message; do
    if [[ "$MODE" == decisions && "$key" == "$CORRELATION" ]] ||
       [[ "$MODE" == audit && "|$AUDIT_CORRELATIONS|" == *"|$key|"* ]]; then
      printf "%s\n" "$message"
    fi
  done < /tmp/read.log
fi'
  check_pod="ooh-stage-check-$(date +%s)-$RANDOM"
  manifest="$(jq -n --arg namespace "$PLATFORM_NAMESPACE" --arg name "$check_pod" --arg mode "$mode" --arg event "$event" --arg correlation "$correlation_id" --arg script "$script" --arg audit_correlations "$audit_correlations" --arg audit_partitions "$audit_partitions" --arg decision_partitions "$decision_partitions" '
    {apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:$namespace},spec:{restartPolicy:"Never",activeDeadlineSeconds:100,automountServiceAccountToken:false,
    securityContext:{runAsNonRoot:true,runAsUser:1001,runAsGroup:1001,fsGroup:1001,seccompProfile:{type:"RuntimeDefault"}},
    containers:[{name:"check",image:"quay.io/strimzi/kafka:1.3.1-kafka-4.3.2",command:["/bin/bash","-ec",$script],
    env:[{name:"PASSWORD",valueFrom:{secretKeyRef:{name:"ooh-stage-check",key:"password"}}},{name:"MODE",value:$mode},{name:"EVENT",value:$event},{name:"CORRELATION",value:$correlation},{name:"AUDIT_CORRELATIONS",value:$audit_correlations},{name:"AUDIT_PARTITIONS",value:$audit_partitions},{name:"DECISION_PARTITIONS",value:$decision_partitions}],
    resources:{requests:{cpu:"100m",memory:"128Mi"},limits:{cpu:"500m",memory:"512Mi"}},
    securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"tmp",mountPath:"/tmp"}]}],
    volumes:[{name:"tmp",emptyDir:{medium:"Memory",sizeLimit:"64Mi"}}]}}')" || return 1
  printf '%s' "$manifest" | kubectl create -f - >/dev/null || return 1
  local deadline=$((SECONDS + 110))
  while ((SECONDS < deadline)); do
    phase="$(kubectl -n "$PLATFORM_NAMESPACE" get pod "$check_pod" -o jsonpath='{.status.phase}')" || break
    [[ "$phase" != Succeeded && "$phase" != Failed ]] || break
    sleep 2
  done
  if [[ "$phase" == Succeeded ]]; then
    output="$(kubectl -n "$PLATFORM_NAMESPACE" logs "$check_pod" -c check)" || rc=1
  else
    rc=1
  fi
  kubectl -n "$PLATFORM_NAMESPACE" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null || rc=1
  check_pod=''
  [[ "$rc" == 0 ]] || return 1
  printf '%s' "$output"
)

audit_protection() {
  local primary count role operation expected output rc statement
  primary="$(kubectl -n "$PLATFORM_NAMESPACE" get cluster ooh-pg -o jsonpath='{.status.currentPrimary}')" || return 1
  [[ "$primary" =~ ^ooh-pg-[0-9]+$ ]] || return 1
  count="$(printf 'SELECT count(*) FROM audit_log;\n' |
    kubectl -n "$PLATFORM_NAMESPACE" exec -i "$primary" -c postgres -- psql -X -U postgres -d controlcentre -At -v ON_ERROR_STOP=1 2>/dev/null)" || return 1
  [[ "$count" =~ ^[0-9]+$ && "$count" != 0 ]] || return 1
  for role in controlcentre_app controlcentre; do
    if [[ "$role" == controlcentre_app ]]; then expected=42501; else expected=P0001; fi
    for operation in UPDATE DELETE; do
      if [[ "$operation" == UPDATE ]]; then
        statement='UPDATE audit_log SET detail = detail WHERE id = (SELECT min(id) FROM audit_log);'
      else
        statement='DELETE FROM audit_log WHERE id = (SELECT min(id) FROM audit_log);'
      fi
      # ON_ERROR_STOP stays off so ROLLBACK is sent even after a refused statement.
      output="$(printf 'BEGIN;\nSET ROLE %s;\n%s\nROLLBACK;\n' "$role" "$statement" |
        kubectl -n "$PLATFORM_NAMESPACE" exec -i "$primary" -c postgres -- \
          psql -X -U postgres -d controlcentre -v ON_ERROR_STOP=0 -v VERBOSITY=verbose 2>&1)" || return 1
      rc=0
      [[ "$output" == *"ERROR:  $expected:"* && "$output" == *ROLLBACK* ]] || rc=1
      if [[ "$role" == controlcentre_app ]]; then
        [[ "$output" == *'permission denied'* ]] || rc=1
      else
        [[ "$output" == *'Audit log is append-only'* ]] || rc=1
      fi
      result "$rc" "audit $operation refused as $role" 'expected database permission denial for the app or trigger refusal for the owner; review migrations and privileges'
    done
  done
}

uuid() { [[ "$1" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; }
expect_request() {
  local principal="$1" method="$2" path="$3" expected="$4" label="$5" data="${6:-}" rc=0
  request "$principal" "$method" "$path" "$data" && [[ "$status" == "$expected" ]] || rc=1
  require "$rc" "$label" "expected HTTP $expected; inspect the API contract and Control Centre logs privately"
}
rc=0
kafka start >/dev/null || rc=1
require "$rc" 'start Kafka check at newest offsets' 'check Kafka access and ensure no other ooh-stage-check consumer is running; retry this check'
expect_request admin GET '/api/admin/models?limit=200' 200 'read check model entries'
old_models="$(jq -er '[.[] | select(.model_id == "stage-check") | .model_entry_id] | .[]' <<< "$body")" || old_models=''
while IFS= read -r old_id; do
  [[ -n "$old_id" ]] || continue
  uuid "$old_id" || stop "model response has an invalid id; inspect the API contract"
  expect_request admin DELETE "/api/admin/models/$old_id" 200 'remove earlier check model entry'
done <<< "$old_models"
model_payload='{"purpose":"chat","tier":99,"role":"backup","location":"cloud","api_type":"stage-check","endpoint_url":"https://stage-check.invalid","model_id":"stage-check","secret_ref":"stage-check-none","rate_limit_per_minute":1,"daily_budget":0}'
expect_request admin POST /api/admin/models 201 'create tier 99 check model entry' "$model_payload"
model_entry_id="$(jq -er '.model_entry_id' <<< "$body")"
uuid "$model_entry_id" || stop "model response has an invalid id; inspect the API contract"
expect_request admin GET '/api/admin/rights?limit=200' 200 'read rights after tier creation'
rc=0
jq -e 'any(.[]; .key == "chat.tier.99")' <<< "$body" >/dev/null || rc=1
require "$rc" 'tier creates its right' 'chat.tier.99 was not returned; inspect the tier creation rule'
grant_payload="$(jq -cn --arg user "$user_id" '{right_key:"chat.tier.99",subject_type:"user",subject_id:$user}')"
expect_request admin POST /api/admin/grants 201 'grant tier 99 to check user' "$grant_payload"
grant_id="$(jq -er '.id' <<< "$body")"
uuid "$grant_id" || stop "grant response has an invalid id; inspect the API contract"
expect_request ooh-harness-api POST /api/rights/check 200 'check granted tier' "$rights_payload"
rc=0
jq -e '.allowed == true and .decided_by == "grant:user"' <<< "$body" >/dev/null || rc=1
require "$rc" 'tier grant allows access' 'expected allowed true from the user grant'
expect_request admin DELETE "/api/admin/grants/$grant_id" 200 'remove tier grant'
expect_request ooh-harness-api POST /api/rights/check 200 'check removed tier grant' "$rights_payload"
rc=0
jq -e '.allowed == false and .decided_by == "no-grant"' <<< "$body" >/dev/null || rc=1
require "$rc" 'removed tier grant refuses access' 'expected allowed false and no-grant'
# Share the idempotent unapproved check identity with the stage check.
pending_user_id='stage-check-access'
observe_payload="$(jq -cn --arg user "$pending_user_id" '{user_id:$user,is_admin:false,name:null,email:null,organisation:null,access_reason:null}')"
expect_request ooh-harness-api POST /api/access/observe 200 'observe unapproved check user' "$observe_payload"
rc=0
jq -e '.status == "pending"' <<< "$body" >/dev/null || rc=1
require "$rc" 'check user stays pending' 'access requests may be closed or the reserved check user approved; inspect admission status before retrying'
everyone_grant_id=''
grant_after=''
while :; do
  expect_request admin GET "/api/admin/grants?right_key=chat.tier.99&limit=200$grant_after" 200 'find existing Everyone check grant'
  everyone_grant_id="$(jq -r '.[] | select(.subject_type == "everyone") | .id' <<< "$body")"
  [[ -z "$everyone_grant_id" && "$(jq 'length' <<< "$body")" == 200 ]] || break
  grant_after="&after=$(jq -er '.[-1].id' <<< "$body")"
done
if [[ -z "$everyone_grant_id" ]]; then
  expect_request admin POST /api/admin/grants 201 'grant Everyone the reserved check tier' '{"right_key":"chat.tier.99","subject_type":"everyone"}'
  everyone_grant_id="$(jq -er '.id' <<< "$body")"
fi
uuid "$everyone_grant_id" || stop "Everyone check grant has an invalid id; inspect it before retrying"
expect_request ooh-harness-api GET "/api/rights/me?user_id=$pending_user_id" 200 'read pending user rights with Everyone'
rc=0
jq -e '(.chat_tiers | length) == 0 and (.skills | length) == 0 and .image == false' <<< "$body" >/dev/null || rc=1
require "$rc" 'Everyone gives pending users nothing' 'an unapproved person received rights; inspect the approval gate'
expect_request ooh-harness-api GET "/api/rights/me?user_id=$user_id" 200 'read approved user rights with Everyone'
rc=0
jq -e '.chat_tiers | index(99) != null' <<< "$body" >/dev/null || rc=1
require "$rc" 'Everyone gives approved users the check tier' 'adding the check user grant did not approve access, or Everyone was not applied'
expect_request admin DELETE "/api/admin/grants/$everyone_grant_id" 200 'remove Everyone check grant'
expect_request admin DELETE "/api/admin/models/$model_entry_id" 200 'remove check model entry'

skill_manifest="$(cat contracts/skills/slides/manifest.json)"
rc=0
request admin POST /api/admin/skills "$skill_manifest" && [[ "$status" == 200 || "$status" == 201 ]] &&
  jq -e '.name == "slides" and .right == "skill.slides"' <<< "$body" >/dev/null || rc=1
require "$rc" 'register Slides skill' 'expected the Slides manifest, with HTTP 200 on an unchanged repeat or 201 when created'
slides_created=false
[[ "$status" != 201 ]] || slides_created=true
expect_request ooh-harness-api GET "/api/skills?user_id=$user_id" 200 'list skills without a grant'
rc=0
jq -e 'type == "array" and all(.[]; .name != "slides")' <<< "$body" >/dev/null || rc=1
require "$rc" 'Slides hidden without its grant' 'check for an everyone grant or a skill rights error'
skill_grant_payload="$(jq -cn --arg user "$user_id" '{right_key:"skill.slides",subject_type:"user",subject_id:$user}')"
expect_request admin POST /api/admin/grants 201 'grant Slides to check user' "$skill_grant_payload"
skill_grant_id="$(jq -er '.id' <<< "$body")"
uuid "$skill_grant_id" || stop "grant response has an invalid id; inspect the API contract"
expect_request ooh-harness-api GET "/api/skills?user_id=$user_id" 200 'list skills with a grant'
rc=0
jq -e 'any(.[]; .name == "slides" and .right == "skill.slides")' <<< "$body" >/dev/null || rc=1
require "$rc" 'Slides visible with its grant' 'expected the Slides skill in the allowed list'
expect_request admin DELETE "/api/admin/grants/$skill_grant_id" 200 'remove check Slides grant'

# Page before deciding rows, since decisions change the pending result set.
before=''
while :; do
  expect_request admin GET "/api/admin/approvals?status=pending&limit=200$before" 200 'read pending approvals for stale checks'
  pending_page="$body"
  jq -e 'type == "array"' <<< "$pending_page" >/dev/null || stop "approval list is not an array; inspect the API contract"
  stale_ids="$(jq -r '.[] | select(.action == "stage.check") | .id' <<< "$pending_page")"
  while IFS= read -r stale_id; do
    [[ -n "$stale_id" ]] || continue
    uuid "$stale_id" || stop "approval response has an invalid id; inspect the API contract"
    expect_request admin POST "/api/admin/approvals/$stale_id/decision" 200 'reject stale stage check' '{"approved":false,"note":"stale stage check"}'
  done <<< "$stale_ids"
  [[ "$(jq 'length' <<< "$pending_page")" == 200 ]] || break
  cursor="$(jq -er 'last | .created_at + "," + .id' <<< "$pending_page")"
  next_before="&before=$(printf '%s' "$cursor" | form_encode)"
  [[ "$next_before" != "$before" ]] || stop "approval paging did not advance; inspect the API contract"
  before="$next_before"
done
result 0 'stale pending stage checks rejected' ''

correlation_id="$(cat /proc/sys/kernel/random/uuid)"
event_id="$(cat /proc/sys/kernel/random/uuid)"
event="$(jq -cn --arg id "$event_id" --arg correlation "$correlation_id" --arg user "$user_id" --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{event_id:$id,type:"approval.requested",version:1,occurred_at:$time,correlation_id:$correlation,user_id:$user,producer:"ooh-stage-check",payload:{action:"stage.check",details:{},risk:"low",requested_by:"stage-check"}}')"
rc=0
kafka publish "$event" >/dev/null || rc=1
require "$rc" 'publish duplicate approval request' 'check the ooh-stage-check KafkaUser and approvals.requested topic'
deadline=$((SECONDS + 60))
found=false
while ((SECONDS < deadline)); do
  if request admin GET "/api/admin/approvals?correlation_id=$correlation_id&limit=200" && [[ "$status" == 200 ]] &&
    jq -e 'length > 0' <<< "$body" >/dev/null; then found=true; break; fi
  sleep 2
done
rc=0
[[ "$found" == true ]] || rc=1
require "$rc" 'approval received within 60 seconds' 'inspect Control Centre consumer, retry and outbox logs'
sleep 10
expect_request admin GET "/api/admin/approvals?correlation_id=$correlation_id&limit=200" 200 'read approvals after duplicate processing'
rc=0
jq -e --arg event "$event_id" --arg correlation "$correlation_id" \
  'length == 1 and .[0].status == "pending" and .[0].request_event_id == $event and .[0].correlation_id == $correlation' <<< "$body" >/dev/null || rc=1
require "$rc" 'duplicate event creates one pending approval' 'expected exactly one pending row for the event'
approval_id="$(jq -er '.[0].id' <<< "$body")"
uuid "$approval_id" || stop "approval response has an invalid id; inspect the API contract"
expect_request admin POST "/api/admin/approvals/$approval_id/decision" 200 'approve the check request' '{"approved":true,"note":"Stage check"}'
rc=0
jq -e '.status == "approved"' <<< "$body" >/dev/null || rc=1
require "$rc" 'approval decision saved' 'expected approved status'
# Poll the topic because publication is asynchronous through the outbox.
deadline=$((SECONDS + 60))
found=false
while ((SECONDS < deadline)); do
  messages="$(kafka decisions)" || break
  if printf '%s\n' "$messages" | jq -se --arg correlation "$correlation_id" --arg user "$user_id" \
    'any(.[]; .type == "approval.decided" and .version == 1 and .producer == "control-centre" and .correlation_id == $correlation and .user_id == $user and .payload.approved == true)' >/dev/null 2>&1; then found=true; break; fi
done
rc=0
[[ "$found" == true ]] || rc=1
require "$rc" 'approval decision published with its correlation id' 'inspect Control Centre outbox and Kafka access'

audit_rows='[]'
for audit_check in grant model decision slides; do
  case "$audit_check" in
    grant) path='/api/admin/audit?target=chat.tier.99&action=grant.created&limit=200' ;;
    model) path='/api/admin/audit?target=stage-check&action=model.created&limit=200' ;;
    decision) path="/api/admin/audit?target=$approval_id&action=approval.decided&limit=200" ;;
    slides) path='/api/admin/audit?target=slides&limit=200' ;;
  esac
  expect_request admin GET "$path" 200 "query $audit_check audit"
  row="$(jq -ce --arg check "$audit_check" --arg grant "$grant_id" --arg model "$model_entry_id" '
    [.[] | select(if $check == "slides" then .target == "slides" and (.action == "skill.registered" or .action == "skill.updated")
      elif $check == "grant" then .detail.after.id == $grant
      elif $check == "model" then .detail.after.model_entry_id == $model
      else true end)] | first | select(. != null)
  ' <<< "$body")" || { result 1 "$audit_check audit row exists" 'expected matching audit row; inspect the write transaction'; stop "audit query did not find the expected row"; }
  if [[ "$audit_check" != slides || "$slides_created" == true ]]; then
    audit_rows="$(printf '%s\n%s\n' "$audit_rows" "$row" | jq -cs '.[0] + [.[1]]')"
  fi
  result 0 "$audit_check audit row exists" ''
done
audit_correlations="$(jq -r '[.[].correlation_id] | unique | join("|")' <<< "$audit_rows")"
deadline=$((SECONDS + 60))
found=false
while ((SECONDS < deadline)); do
  messages="$(kafka audit)" || break
  if printf '%s\n%s\n' "$audit_rows" "$messages" | jq -se '
    .[0] as $expected | .[1:] as $events |
    all($expected[]; . as $row | any($events[];
      .type == "audit.event" and .version == 1 and .producer == "control-centre" and .correlation_id == $row.correlation_id and
      .payload.actor == $row.actor and .payload.action == $row.action and .payload.target == $row.target and .payload.outcome == $row.outcome))
  ' >/dev/null 2>&1; then found=true; break; fi
done
rc=0
[[ "$found" == true ]] || rc=1
require "$rc" 'matching audit events from this run published' 'inspect the outbox, audit.events and retention; matching audit messages must be present'
rc=0
audit_protection || rc=1
require "$rc" 'audit protection checks completed with rollback' 'check PostgreSQL pod access and audit rows, then review migration protections'
((failed == 0)) || stop "Control Centre checks failed; fix every FAIL line before repeating"
stage_check_end || stop "check client did not disable"
printf 'DONE\n'
