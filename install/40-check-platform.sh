#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "step failed; see README troubleshooting and re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for tool in kubectl jq curl flock; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
# shellcheck source=/dev/null
source deploy/values/do.env
[[ -f "$HOME/.config/ooh/do.env" ]] || stop "local settings missing; copy install/ooh.env.example as described in README"
# shellcheck source=/dev/null
source "$HOME/.config/ooh/do.env"
[[ -n "${LETSENCRYPT_EMAIL:-}" ]] || stop "local setting LETSENCRYPT_EMAIL is empty; fill it in as described in README"
failed=0
result() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s: %s\n' "$2" "$3"; failed=1; fi
}
for namespace in "$PLATFORM_NAMESPACE" cert-manager; do
  rc=0
  pods="$(kubectl -n "$namespace" get pods -o json 2>/dev/null)" || rc=1
  # Completed import/bootstrap jobs are not running pods.
  jq -e '[.items[] | select(.status.phase != "Succeeded")] | length > 0 and all(.[]; any(.status.conditions[]?; .type == "Ready" and .status == "True"))' <<< "$pods" >/dev/null 2>&1 || rc=1
  result "$rc" "pods $namespace" 'pods are not Ready; inspect pod status and logs'
done
for name in model-gateway slides-worker; do
  replicas="$(kubectl -n "$APPS_NAMESPACE" get deployment "$name" --ignore-not-found -o jsonpath='{.spec.replicas}')"
  if [[ "$replicas" == 0 ]]; then result 1 "$name scaled to 0 (run install/79-demo.sh restore)" 'restore the demo before checking'; fi
done
jaeger_pods="$(kubectl -n "$PLATFORM_NAMESPACE" get pods -l app=jaeger -o json)"
restarts="$(jq '[.items[].status.containerStatuses[]?.restartCount] | add // 0' <<< "$jaeger_pods")"
if ((restarts > 0)); then printf 'INFO jaeger restarted %s times\n' "$restarts"; fi
for entry in "$PLATFORM_NAMESPACE auth" "$APPS_NAMESPACE harness" "$APPS_NAMESPACE admin"; do
  read -r namespace name <<< "$entry"
  rc=0
  cert="$(kubectl -n "$namespace" get certificate "$name-tls" -o json 2>/dev/null)" || rc=1
  jq -e '.spec.issuerRef.name == "letsencrypt-prod" and (.metadata.generation as $g | any(.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $g))' <<< "$cert" >/dev/null 2>&1 || rc=1
  result "$rc" "production certificate $name" 'certificate is not Ready with production issuer; inspect certificate events'
done
control_centre="$(kubectl -n "$APPS_NAMESPACE" get deployment control-centre --ignore-not-found -o name)"
admin_api="https://admin.$DOMAIN/api/"
admin_expected=200
if [[ -n "$control_centre" ]]; then
  admin_api="https://admin.$DOMAIN/api/rights/me?user_id=x"
  admin_expected=401
fi
real_app() {
  local deployment
  deployment="$(kubectl -n "$APPS_NAMESPACE" get deployment "$1" --ignore-not-found -o json)" || return 1
  [[ -n "$deployment" ]] && jq -e '.spec.template.metadata.labels["ooh/app"] == "real"' <<< "$deployment" >/dev/null
}
harness_api="https://harness.$DOMAIN/api/"
harness_expected=200
if real_app harness-api; then
  harness_api="https://harness.$DOMAIN/api/conversations"
  harness_expected=401
fi
for url in "https://harness.$DOMAIN/" "$harness_api" "https://admin.$DOMAIN/" "$admin_api"; do
  expected=200
  [[ "$url" != "$admin_api" ]] || expected="$admin_expected"
  [[ "$url" != "$harness_api" ]] || expected="$harness_expected"
  reply="$(curl --connect-timeout 10 --max-time 30 -sS -w '\n%{http_code}' "$url" 2>/dev/null || true)"
  status="${reply##*$'\n'}"
  body="${reply%$'\n'*}"
  rc=0; [[ "$status" == "$expected" ]] || rc=1
  if [[ "$url" == "https://harness.$DOMAIN/" ]] && real_app workspace; then
    [[ "$body" == *'<app-root'* ]] || rc=1
  elif [[ "$url" == "https://admin.$DOMAIN/" ]] && real_app admin-console; then
    [[ "$body" == *'<app-root'* ]] || rc=1
  fi
  result "$rc" "HTTPS $url" "expected HTTP $expected with trusted TLS and the app root for real apps; check ingress, certificate and deployment"
done
issuer="https://auth.$DOMAIN/realms/ooh"
rc=0
body="$(curl --connect-timeout 10 --max-time 30 -fsS "$issuer/.well-known/openid-configuration" 2>/dev/null)" || rc=1
jq -e --arg issuer "$issuer" '.issuer == $issuer' <<< "$body" >/dev/null 2>&1 || rc=1
result "$rc" 'OIDC issuer and trusted TLS' 'expected ooh issuer; check realm import, hostname and certificate'
while read -r name partitions retention <&3; do
  resource="${name//./-}"
  rc=0
  topic="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkatopic "$resource" -o json 2>/dev/null)" || rc=1
  jq -e --arg name "$name" --argjson p "$partitions" --argjson r "$retention" '.spec.topicName == $name and .spec.partitions == $p and .spec.replicas == 1 and .spec.config["retention.ms"] == $r and .spec.config["min.insync.replicas"] == 1 and (.metadata.generation as $g | .status.observedGeneration == $g) and any(.status.conditions[]?; .type == "Ready" and .status == "True")' <<< "$topic" >/dev/null 2>&1 || rc=1
  result "$rc" "topic $name" 'topic configuration or reconciliation differs; re-run platform apply and inspect KafkaTopic'
done 3<<'TOPICS'
skill.requests.slides 3 604800000
skill.results 3 604800000
approvals.requested 3 2592000000
approvals.decided 3 2592000000
audit.events 3 2592000000
dlq.skill.requests.slides 1 2592000000
dlq.skill.results 1 2592000000
dlq.approvals.requested 1 2592000000
dlq.approvals.decided 1 2592000000
dlq.audit.events 1 2592000000
ooh.smoke 1 3600000
chat.messages 3 604800000
dlq.chat.messages 1 2592000000
TOPICS
# shellcheck disable=SC2016 # Expansion occurs only in the Keycloak pod.
check_enabled="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- sh -c '
  set -eu; set +x; umask 077
  directory="$(mktemp -d /tmp/ooh-platform-check.XXXXXXXX)"
  trap '\''rm -rf -- "$directory"'\'' EXIT
  /opt/keycloak/bin/kcadm.sh config credentials --config "$directory/config" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  /opt/keycloak/bin/kcadm.sh get clients -r ooh -q clientId=ooh-stage-check --fields enabled --config "$directory/config" 2>/dev/null
' 2>/dev/null)" || check_enabled=''
rc=0
if ! jq -e 'length == 1 and .[0].enabled == false' <<< "$check_enabled" >/dev/null 2>&1; then
  lock_pid="$(cat "$HOME/.config/ooh/stage-check.lock" 2>/dev/null || true)"
  jq -e 'length == 1 and .[0].enabled == true' <<< "$check_enabled" >/dev/null 2>&1 || rc=1
  [[ "$lock_pid" =~ ^[0-9]+$ ]] && kill -0 "$lock_pid" 2>/dev/null || rc=1
  if [[ -f "$HOME/.config/ooh/stage-check.lock" ]]; then
    exec {check_lock}<>"$HOME/.config/ooh/stage-check.lock"
    if flock -n "$check_lock"; then rc=1; flock -u "$check_lock"; fi
    exec {check_lock}>&-
  else rc=1; fi
fi
if ((rc == 0)); then result 0 'ooh-stage-check disabled or check running' ''; else result 1 'ooh-stage-check enabled with no check running' 'run install/77-check-stage-3.sh <tag> once, then run 40 again'; fi
check_pod=''
check_namespace=${PLATFORM_NAMESPACE}
cleanup() {
  if [[ -n "$check_pod" ]]; then kubectl -n "$check_namespace" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
run_pod() {
  local image="$1" script="$2" env="$3" namespace="${4:-${PLATFORM_NAMESPACE}}" pvc="${5:-}" rc=0
  check_namespace="$namespace"
  check_pod="ooh-check-$(date +%s)-$RANDOM"
  jq -n --arg name "$check_pod" --arg image "$image" --arg script "$script" --argjson env "$env" --arg namespace "$namespace" --arg pvc "$pvc" '{apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:$namespace},spec:{restartPolicy:"Never",activeDeadlineSeconds:150,automountServiceAccountToken:false,securityContext:{runAsNonRoot:true,runAsUser:1001,runAsGroup:1001,fsGroup:1001,seccompProfile:{type:"RuntimeDefault"}},containers:[{name:"check",image:$image,command:["/bin/bash","-ec",$script],env:$env,resources:{requests:{cpu:"100m",memory:"128Mi"},limits:{cpu:"500m",memory:"512Mi"}},securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"tmp",mountPath:"/tmp"}]}],volumes:[{name:"tmp",emptyDir:{medium:"Memory",sizeLimit:"64Mi"}}]}} | if $pvc != "" then .spec.volumes += [{name:"files",persistentVolumeClaim:{claimName:$pvc}}] | .spec.containers[0].volumeMounts += [{name:"files",mountPath:"/files"}] else . end' | kubectl create -f - >/dev/null
  for ((attempt=0; attempt<90; attempt++)); do
    phase="$(kubectl -n "$check_namespace" get pod "$check_pod" -o jsonpath='{.status.phase}')"
    [[ "$phase" != Succeeded && "$phase" != Failed ]] || break
    sleep 2
  done
  [[ "$phase" == Succeeded ]] || rc=1
  cleanup
  check_pod=''
  return "$rc"
}
rc=0
jaeger="$(kubectl -n "$PLATFORM_NAMESPACE" get deployment jaeger -o json)" || rc=1
jq -e '.metadata.generation <= (.status.observedGeneration // 0) and .spec.replicas == 1 and .status.updatedReplicas == 1 and .status.readyReplicas == 1 and .status.availableReplicas == 1' <<< "$jaeger" >/dev/null || rc=1
trace_image="$(kubectl -n "$APPS_NAMESPACE" get deployment slides-worker -o jsonpath='{.spec.template.spec.containers[0].image}')" || rc=1
trace_script="$(cat <<'POD'
python - <<'PYCODE'
import json, secrets, time, urllib.request
try:
    trace = secrets.token_hex(16)
    now = time.time_ns()
    payload = {'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'platform-check'}}]}, 'scopeSpans':[{'spans':[{'traceId':trace,'spanId':secrets.token_hex(8),'name':'platform check','kind':1,'startTimeUnixNano':str(now),'endTimeUnixNano':str(now+1000000)}]}]}]}
    request = urllib.request.Request('http://jaeger:4318/v1/traces', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://jaeger:16686/api/v3/traces/'+trace, timeout=5) as response:
                result = json.load(response)
            spans = [s for r in result['result']['resourceSpans'] for scope in r.get('scopeSpans',[]) for s in scope.get('spans',[])]
            assert any(s['traceId'] == trace for s in spans)
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError('trace not found')
except Exception:
    raise SystemExit('Jaeger check failed') from None
PYCODE
POD
)"
if ((rc == 0)); then run_pod "$trace_image" "$trace_script" '[]' || rc=1; fi
result "$rc" 'Jaeger Ready and OTLP HTTP span readable through query API inside cluster' 're-run 30; inspect Jaeger readiness, configuration and logs'
# shellcheck disable=SC2016 # Expanded inside the check pod.
kafka_script='set -euo pipefail
umask 077
printf "security.protocol=SASL_PLAINTEXT\nsasl.mechanism=SCRAM-SHA-512\nsasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username=\"ooh-smoke\" password=\"%s\";\n" "$PASSWORD" > /tmp/client.properties
unset PASSWORD
cd /opt/kafka/bin
message="ooh-smoke-$(date +%s)-$RANDOM"
printf "%s\n" "$message" | ./kafka-console-producer.sh --bootstrap-server ooh-kafka-kafka-bootstrap:9092 --topic ooh.smoke --producer.config /tmp/client.properties >/tmp/produce.log 2>&1
./kafka-console-consumer.sh --bootstrap-server ooh-kafka-kafka-bootstrap:9092 --topic ooh.smoke --group ooh-smoke --from-beginning --timeout-ms 15000 --consumer.config /tmp/client.properties > /tmp/read.log 2>/tmp/consume.log || true
found=false
while IFS= read -r line; do [[ "$line" != "$message" ]] || found=true; done < /tmp/read.log
[[ "$found" == true ]]
printf "%s\n" "$message" | ./kafka-console-producer.sh --bootstrap-server ooh-kafka-kafka-bootstrap:9092 --topic skill.results --producer.config /tmp/client.properties > /tmp/denied.log 2>&1 || true
log="$(cat /tmp/denied.log)"
[[ "$log" == *TopicAuthorizationException* ]]'
env='[{"name":"PASSWORD","valueFrom":{"secretKeyRef":{"name":"ooh-smoke","key":"password"}}}]'
rc=0
run_pod quay.io/strimzi/kafka:1.3.1-kafka-4.3.2 "$kafka_script" "$env" || rc=1
result "$rc" 'Kafka smoke write/read and forbidden skill.results write' 'smoke did not round-trip or denial was not TopicAuthorizationException; inspect Kafka user and ACLs'
env='[{"name":"PGPASSWORD","valueFrom":{"secretKeyRef":{"name":"keycloak-db","key":"password"}}},{"name":"PGSSLMODE","value":"require"}]'
rc=0
# shellcheck disable=SC2016 # Expanded inside the check pod.
run_pod ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie '[[ "$(psql -h ooh-pg-rw -U keycloak -d keycloak -Atc "SELECT 1")" == 1 ]]' "$env" || rc=1
result "$rc" 'PostgreSQL SELECT 1 as keycloak' 'connection or query failed; check database role and secret names'
rc=0
# shellcheck disable=SC2016 # Expanded inside the storage check pod.
run_pod ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie 'set -euo pipefail
umask 077
mkdir -p /files/checks
file="/files/checks/stage0-$(date -u +%s%N).txt"
message="open-office-harness storage check"
printf "%s\n" "$message" > "$file"
[[ "$(cat "$file")" == "$message" ]]' '[]' "$APPS_NAMESPACE" ooh-files || rc=1
result "$rc" 'storage PVC ooh-files write/read under checks/' "check ooh-files PVC, local-path provisioner, disk space and pod volume permissions in $APPS_NAMESPACE; check files are retained"
check_retention() {
  local namespace="$1" label="$2" claims name volume pv rc=0
  shift 2
  claims="$(kubectl -n "$namespace" get pvc "$@" -o json 2>/dev/null)" || rc=1
  jq -e '.items | length > 0 and all(.[]; .status.phase == "Bound" and (.spec.volumeName // "") != "")' <<< "$claims" >/dev/null 2>&1 || rc=1
  while IFS=$'\t' read -r name volume <&3; do
    [[ -n "$volume" ]] || continue
    pv="$(kubectl get pv "$volume" -o json 2>/dev/null)" || rc=1
    jq -e --arg namespace "$namespace" --arg name "$name" '.spec.persistentVolumeReclaimPolicy == "Retain" and .spec.storageClassName == "local-path" and .status.phase == "Bound" and .spec.claimRef.namespace == $namespace and .spec.claimRef.name == $name' <<< "$pv" >/dev/null 2>&1 || rc=1
  done 3< <(jq -r '.items[]? | select(.status.phase == "Bound") | [.metadata.name,.spec.volumeName] | @tsv' <<< "$claims" 2>/dev/null)
  result "$rc" "PV retention $label" 'expected bound local-path PVs with Retain; re-run step 6 and inspect claims and PVs'
}
check_retention "$PLATFORM_NAMESPACE" Kafka -l strimzi.io/cluster=ooh-kafka
check_retention "$PLATFORM_NAMESPACE" PostgreSQL -l cnpg.io/cluster=ooh-pg
check_retention "$APPS_NAMESPACE" ooh-files --field-selector metadata.name=ooh-files
((failed == 0)) || stop "platform checks failed; fix the FAIL lines above and re-run"
printf 'DONE\n'
