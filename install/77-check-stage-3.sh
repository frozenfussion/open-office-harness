#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "Stage 3 check could not continue; fix the last FAIL or inspect readiness and retry"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
# shellcheck source=install/lib/stage-check.sh
source install/lib/stage-check.sh
[[ $# == 1 && "$1" =~ ^[a-f0-9]{12}$ ]] || stop 'usage: install/77-check-stage-3.sh <12-character image tag>'
tag="$1"
for tool in kubectl curl jq flock python3; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
failed=0
result() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s: %s\n' "$2" "$3"; failed=1; fi
}
require() { result "$@"; [[ "$1" == 0 ]] || stop "cannot continue after $2; fix the FAIL line and retry"; }
tmp="$(mktemp -d)"
check_pod=''; check_namespace=''; forward_pids=(); routing_grants=()
cleanup() {
  if ((${#routing_grants[@]})); then remove_routing_grants || printf "FAIL temporary routing grants could not be removed; inspect check-user grants in People & rights\n" >&2; fi
  stage_check_end || true
  local pid
  for pid in "${forward_pids[@]}"; do kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; done
  [[ -z "$check_pod" ]] || kubectl -n "$check_namespace" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  rm -rf -- "$tmp"
}
trap 'cleanup; ooh_target_cleanup' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
stage_check_begin || stop 'temporary check client could not start'
issuer="https://auth.$DOMAIN/realms/ooh"
admin_base="https://admin.$DOMAIN"
harness_base="https://harness.$DOMAIN"
forward() {
  local service="$1" local_port="$2" target="$3" pid
  if (exec 3<>"/dev/tcp/127.0.0.1/$local_port") 2>/dev/null; then stop "local port $local_port is busy; stop the old check and retry"; fi
  (exec {STAGE_CHECK_FD}>&-; exec kubectl -n "$APPS_NAMESPACE" port-forward --address 127.0.0.1 "service/$service" "$local_port:$target") >"$tmp/forward-$local_port.log" 2>&1 &
  pid=$!; forward_pids+=("$pid")
  for ((attempt=0; attempt<30; attempt++)); do
    if curl -fsS --max-time 1 "http://127.0.0.1:$local_port/health" >/dev/null 2>&1; then return 0; fi
    kill -0 "$pid" 2>/dev/null || stop "port-forward for $service failed; inspect readiness"
    sleep 1
  done
  stop "port-forward for $service is not ready"
}
service_token() {
  local client="$1" id secret reply
  id="$(_stage_check_admin get clients -r ooh -q "clientId=$client" --fields id | jq -er 'if length == 1 then .[0].id else error("missing") end')" || return 1
  secret="$(_stage_check_admin get "clients/$id/client-secret" -r ooh | jq -jer '.value | @uri')" || return 1
  reply="$(printf 'grant_type=client_credentials&client_id=%s&client_secret=%s' "$client" "$secret" |
    curl --connect-timeout 10 --max-time 30 -fsS -H 'Content-Type: application/x-www-form-urlencoded' --data-binary @- "$issuer/protocol/openid-connect/token" 2>/dev/null)" || return 1
  jq -jer '.access_token | select(type == "string" and test("^[A-Za-z0-9_.-]+$"))' <<< "$reply"
}
request() {
  local principal="$1" method="$2" url="$3" data="${4:-}" token='' reply
  case "$principal" in
    admin) token="$(stage_check_token ooh-control-centre)" || return 1 ;;
    check) token="$(stage_check_token ooh-harness-api)" || return 1 ;;
    anonymous) ;;
    *) token="$(service_token "$principal")" || return 1 ;;
  esac
  reply="$( {
    [[ -z "$token" ]] || printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'header = "Content-Type: application/json"\n'
    [[ -z "${job_id:-}" ]] || printf 'header = "X-Correlation-Id: %s"\n' "$job_id"
    [[ -z "$data" ]] || { printf 'data = '; printf '%s' "$data" | jq -Rs .; }
  } | curl --config - --connect-timeout 10 --max-time 930 -sS -X "$method" "$url" -w '\n%{http_code}' 2>/dev/null)" || return 1
  status="${reply##*$'\n'}"; body="${reply%$'\n'*}"
}
remove_routing_grants() {
  local id rc=0
  local remaining=()
  for id in "${routing_grants[@]}"; do
    if ! request admin DELETE "$admin_base/api/admin/grants/$id" || [[ "$status" != 200 ]]; then
      remaining+=("$id"); rc=1
    fi
  done
  routing_grants=("${remaining[@]}")
  return "$rc"
}
# Pods receive real credentials only through Secret environment references.
run_pod() {
  local namespace="$1" image="$2" script="$3" env="$4" files="${5:-false}" phase='' deadline rc=0
  check_namespace="$namespace"; check_pod="ooh-stage3-$(date +%s)-$RANDOM"
  jq -n --arg namespace "$namespace" --arg name "$check_pod" --arg image "$image" --arg script "$script" --argjson env "$env" --argjson files "$files" '
    {apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:$namespace},spec:{restartPolicy:"Never",activeDeadlineSeconds:300,automountServiceAccountToken:false,
    securityContext:{runAsNonRoot:true,runAsUser:10001,runAsGroup:10001,seccompProfile:{type:"RuntimeDefault"}},
    containers:[{name:"check",image:$image,command:["/bin/sh","-ec",$script],env:$env,
    resources:{requests:{cpu:"50m",memory:"96Mi"},limits:{cpu:"500m",memory:"512Mi"}},
    securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"tmp",mountPath:"/tmp"}]}],
    volumes:[{name:"tmp",emptyDir:{medium:"Memory",sizeLimit:"32Mi"}}]}} |
    if $files then .spec.volumes += [{name:"files",persistentVolumeClaim:{claimName:"ooh-files",readOnly:true}}] | .spec.containers[0].volumeMounts += [{name:"files",mountPath:"/files",readOnly:true}] else . end' |
    kubectl create -f - >/dev/null || return 1
  deadline=$((SECONDS + 310))
  while ((SECONDS < deadline)); do
    phase="$(kubectl -n "$namespace" get pod "$check_pod" -o jsonpath='{.status.phase}')" || break
    [[ "$phase" != Succeeded && "$phase" != Failed ]] || break
    sleep 2
  done
  [[ "$phase" == Succeeded ]] || rc=1
  pod_output=''
  if ((rc == 0)); then pod_output="$(kubectl -n "$namespace" logs "$check_pod" -c check)" || rc=1; fi
  kubectl -n "$namespace" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null || rc=1
  check_pod=''
  return "$rc"
}
slides_image="ghcr.io/frozenfussion/ooh-slides-worker:$tag"
rc=0
deployments="$(kubectl -n "$APPS_NAMESPACE" get deployments -o json)" || rc=1
jq -e '(.items | length > 0) and all(.items[]; .metadata.generation <= (.status.observedGeneration // 0) and (.spec.replicas // 1) > 0 and .status.updatedReplicas == .spec.replicas and .status.readyReplicas == .spec.replicas and .status.availableReplicas == .spec.replicas)' <<< "$deployments" >/dev/null || rc=1
result "$rc" 'all application Deployments Ready on current revision' 'inspect Deployment and pod status'
for name in control-centre model-gateway harness-api workspace admin-console slides-worker audit-writer cost-meter safety-watcher; do
  rc=0
  jq -e --arg name "$name" --arg image "ghcr.io/frozenfussion/ooh-$name:$tag" '[.items[] | select(.metadata.name == $name)] | length == 1 and all(.[]; all(.spec.template.spec.containers[]; .image == $image) and all(.spec.template.spec.initContainers[]?; .image == $image))' <<< "$deployments" >/dev/null || rc=1
  result "$rc" "image $name:$tag" 'run the image workflow for the merge commit, make the package public, and deploy this tag'
done
rc=0
realm="$(_stage_check_admin get realms/ooh --fields displayName,loginTheme)" || rc=1
jq -e '.displayName == "Open Office Harness" and .loginTheme == "ooh"' <<< "$realm" >/dev/null || rc=1
result "$rc" 'realm branding' 're-run install/35-realm-sync.sh'
rc=0
device="$(printf 'client_id=ooh-admin-console' | curl --connect-timeout 10 --max-time 30 -sS --data-binary @- "$issuer/protocol/openid-connect/auth/device" 2>/dev/null)" || rc=1
jq -e '.error == "unauthorized_client" and (has("device_code") | not)' <<< "$device" >/dev/null || rc=1
result "$rc" 'admin device sign-in refused' 're-run install/35-realm-sync.sh'
rc=0
login="$(curl --connect-timeout 10 --max-time 30 -fsS -G "$issuer/protocol/openid-connect/auth" --data-urlencode client_id=ooh-workspace --data-urlencode response_type=code --data-urlencode scope=openid --data-urlencode "redirect_uri=$harness_base/" --data-urlencode code_challenge=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ --data-urlencode code_challenge_method=S256 2>/dev/null)" || rc=1
[[ "$login" == *'/ooh/css/ooh.css'* ]] || rc=1
result "$rc" 'branded login stylesheet' 're-run 30; inspect the theme ConfigMap and Keycloak mount'
# Build expected ACL operations directly from the identity table, never from the manifests being checked.
expected_acls="$(python3 - <<'PY'
import json
from pathlib import Path
result = {}
for line in Path('contracts/identity.md').read_text().splitlines():
    if not line.startswith('| '):
        continue
    fields = [value.strip() for value in line.strip('|').split('|')]
    if len(fields) != 4 or fields[0] in ('Principal', '---') or ' | Write |' in line:
        continue
    name, writes, reads, group = fields
    if name not in ('harness-api','slides-worker','audit-writer','cost-meter','safety-watcher','model-gateway','control-centre','ooh-stage-check'):
        continue
    entries = set()
    for value, operation in ((writes, 'Write'), (reads, 'Read')):
        for topic in value.split(', '):
            if topic != 'none':
                entries.update((('topic', topic, 'literal', operation), ('topic', topic, 'literal', 'Describe')))
    if group != 'none':
        entries.add(('group', group, 'literal', 'Read'))
    result[name] = sorted(entries)
print(json.dumps(result))
PY
)"
for name in harness-api slides-worker audit-writer cost-meter safety-watcher model-gateway control-centre ooh-stage-check; do
  rc=0
  user="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkauser "$name" -o json)" || rc=1
  jq -e --arg name "$name" --argjson expected "$expected_acls" '
    .spec.authentication.type == "scram-sha-512" and .spec.authorization.type == "simple" and
    ([.spec.authorization.acls[] | . as $acl | .operations[] | [$acl.resource.type,$acl.resource.name,$acl.resource.patternType,.]] | sort) == $expected[$name] and
    (.metadata.generation == .status.observedGeneration) and any(.status.conditions[]?; .type == "Ready" and .status == "True")' <<< "$user" >/dev/null || rc=1
  result "$rc" "Kafka ACLs $name" 'compare contracts/identity.md and re-run 30'
done
rc=0
topics="$(kubectl -n "$PLATFORM_NAMESPACE" get kafkatopics -o json)" || rc=1
jq -e '([.items[] | select(.metadata.labels["strimzi.io/cluster"] == "ooh-kafka") | .spec.topicName] | sort) == (["skill.requests.slides","skill.results","approvals.requested","approvals.decided","audit.events","dlq.skill.requests.slides","dlq.skill.results","dlq.approvals.requested","dlq.approvals.decided","dlq.audit.events","chat.messages","dlq.chat.messages","ooh.smoke"] | sort)' <<< "$topics" >/dev/null || rc=1
result "$rc" 'thirteen Kafka topics' 're-run 30'
forward model-gateway 18082 8080
forward control-centre 18081 8081
job_id="$(cat /proc/sys/kernel/random/uuid)"
event_id="$(cat /proc/sys/kernel/random/uuid)"
check_user="stage-check-$job_id"
make_event() {
  jq -cn --arg event "$event_id" --arg correlation "$job_id" --arg user "$check_user" --arg type "$1" --argjson payload "$2" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{event_id:$event,type:$type,version:1,occurred_at:$at,correlation_id:$correlation,user_id:$user,producer:"stage-check",payload:$payload}'
}
slide_event="$(make_event skill.requested '{"skill":"slides","skill_version":"1.0.0","input":{"topic":"The water cycle"}}')"
# The Python client is already bundled in the worker; no check-only dependency.
kafka() {
  local mode="$1" topic="$2" message="${3:-}" correlation="${4:-$job_id}" env script
  env="$(jq -cn --arg mode "$mode" --arg topic "$topic" --arg message "$message" --arg correlation "$correlation" --arg bootstrap "ooh-kafka-kafka-bootstrap.$PLATFORM_NAMESPACE.svc:9092" '[{name:"PASSWORD",valueFrom:{secretKeyRef:{name:"ooh-stage-check",key:"password"}}},{name:"MODE",value:$mode},{name:"TOPIC",value:$topic},{name:"MESSAGE",value:$message},{name:"CORRELATION",value:$correlation},{name:"BOOTSTRAP",value:$bootstrap}]')"
  script="$(cat <<'POD'
python - <<'PY'
import json, os, time
from confluent_kafka import Consumer, Producer, TopicPartition
config = {'bootstrap.servers':os.environ['BOOTSTRAP'], 'security.protocol':'SASL_PLAINTEXT', 'sasl.mechanism':'SCRAM-SHA-512', 'sasl.username':'ooh-stage-check', 'sasl.password':os.environ.pop('PASSWORD')}
try:
    if os.environ['MODE'] == 'write':
        errors = []
        producer = Producer(config)
        producer.produce(os.environ['TOPIC'], key=os.environ['CORRELATION'], value=os.environ['MESSAGE'], on_delivery=lambda error, message: errors.append(error) if error else None)
        assert producer.flush(30) == 0 and not errors
    else:
        consumer = Consumer({**config, 'group.id':'ooh-stage-check', 'enable.auto.commit':False, 'auto.offset.reset':'earliest'})
        metadata = consumer.list_topics(os.environ['TOPIC'], timeout=20)
        consumer.assign([TopicPartition(os.environ['TOPIC'], partition, 0) for partition in metadata.topics[os.environ['TOPIC']].partitions])
        deadline = time.monotonic() + 180
        found = None
        while time.monotonic() < deadline:
            message = consumer.poll(1)
            if message is None: continue
            if message.error(): raise RuntimeError('consume failed')
            value = json.loads(message.value())
            if value.get('correlation_id') == os.environ['CORRELATION']:
                found = value; break
        consumer.close()
        assert found is not None
        assert found['type'] == 'skill.result' and found['payload']['status'] == 'completed'
        print(json.dumps({'event_id':found['event_id'], 'file_key':found['payload']['output']['file_key']}))
except Exception:
    raise SystemExit('check failed') from None
PY
POD
)"
  run_pod "$PLATFORM_NAMESPACE" "$slides_image" "$script" "$env"
}
rc=0
kafka write skill.requests.slides "$slide_event" || rc=1
require "$rc" 'Slides request published' 'inspect worker and Kafka readiness'
rc=0
kafka read skill.results || rc=1
require "$rc" 'Slides result completed within 180 seconds' 'inspect worker, model registry, Gateway, Kafka and file permissions'
first_result="$pod_output"
file_key="$(jq -er '.file_key' <<< "$first_result")"
file_check() {
  local env script
  env="$(jq -cn --arg key "$file_key" '[{name:"FILE_KEY",value:$key}]')"
  script="$(cat <<'POD'
python - <<'PY'
import json, os
from pathlib import Path
from pptx import Presentation
try:
    path = (Path('/files') / os.environ['FILE_KEY']).resolve()
    assert path.is_relative_to('/files/outputs/slides')
    assert path.suffix == '.pptx' and len(Presentation(str(path)).slides) >= 3
    print(json.dumps({'mtime':path.stat().st_mtime_ns}))
except Exception:
    raise SystemExit('file check failed') from None
PY
POD
)"
  run_pod "$APPS_NAMESPACE" "$slides_image" "$script" "$env" true
}
rc=0
file_check || rc=1
require "$rc" 'PowerPoint file opens with at least three slides' 'inspect worker and the file volume'
first_file="$pod_output"
# Read from the end captured before the repeat; an old result is not proof of republishing.
# The repeated event is handled in one pod so the read begins before the write.
repeat_script="$(cat <<'POD'
python - <<'PY'
import json, os, time
from confluent_kafka import Consumer, Producer, TopicPartition
config = {'bootstrap.servers':os.environ['BOOTSTRAP'], 'security.protocol':'SASL_PLAINTEXT', 'sasl.mechanism':'SCRAM-SHA-512', 'sasl.username':'ooh-stage-check', 'sasl.password':os.environ.pop('PASSWORD')}
try:
    consumer = Consumer({**config, 'group.id':'ooh-stage-check', 'enable.auto.commit':False})
    metadata = consumer.list_topics('skill.results', timeout=20)
    partitions = []
    for partition in metadata.topics['skill.results'].partitions:
        tp = TopicPartition('skill.results', partition)
        _, end = consumer.get_watermark_offsets(tp, timeout=20)
        partitions.append(TopicPartition('skill.results', partition, end))
    consumer.assign(partitions)
    errors = []
    producer = Producer(config)
    producer.produce('skill.requests.slides', key=os.environ['CORRELATION'], value=os.environ['MESSAGE'], on_delivery=lambda error, message: errors.append(error) if error else None)
    assert producer.flush(30) == 0 and not errors
    deadline = time.monotonic() + 180
    found = False
    while time.monotonic() < deadline:
        message = consumer.poll(1)
        if message is None: continue
        if message.error(): raise RuntimeError('consume failed')
        value = json.loads(message.value())
        if value.get('correlation_id') == os.environ['CORRELATION']:
            assert value['event_id'] == os.environ['RESULT_ID'] and value['payload']['status'] == 'completed'
            found = True; break
    consumer.close()
    assert found
except Exception:
    raise SystemExit('repeat check failed') from None
PY
POD
)"
repeat_env="$(jq -cn --arg message "$slide_event" --arg correlation "$job_id" --arg result "$(jq -r '.event_id' <<< "$first_result")" --arg bootstrap "ooh-kafka-kafka-bootstrap.$PLATFORM_NAMESPACE.svc:9092" '[{name:"PASSWORD",valueFrom:{secretKeyRef:{name:"ooh-stage-check",key:"password"}}},{name:"MESSAGE",value:$message},{name:"CORRELATION",value:$correlation},{name:"RESULT_ID",value:$result},{name:"BOOTSTRAP",value:$bootstrap}]')"
rc=0
run_pod "$PLATFORM_NAMESPACE" "$slides_image" "$repeat_script" "$repeat_env" && file_check && [[ "$pod_output" == "$first_file" ]] || rc=1
result "$rc" 'repeat has the same result ID and unchanged file modification time' 'inspect worker idempotency'
bad_sent_at="$(date -u +%Y-%m-%dT%H:%M:%S)"
rc=0
kafka write skill.requests.slides 'not json' || rc=1
require "$rc" 'malformed message published' 'inspect Kafka access'
found=false; deadline=$((SECONDS + 60))
while ((SECONDS < deadline)); do
  if request admin GET "$admin_base/api/admin/dead-letters?topic=dlq.skill.requests.slides&limit=200" && [[ "$status" == 200 ]] &&
    jq -e --arg at "$bad_sent_at" 'any(.[]; .original_message == "not json" and .received_at >= $at)' <<< "$body" >/dev/null; then found=true; break; fi
  sleep 2
done
rc=0; [[ "$found" == true ]] || rc=1
result "$rc" 'malformed message appears in dead letters within 60 seconds' 'inspect worker DLQ and Control Centre consumer'
found=false; deadline=$((SECONDS + 60))
while ((SECONDS < deadline)); do
  if request admin GET "$admin_base/api/admin/trail?correlation_id=$job_id&limit=200" && [[ "$status" == 200 ]] &&
    jq -e 'any(.[]; .action == "model.call" and .producer == "model-gateway") and any(.[]; .action == "skill.result" and .producer == "slides-worker")' <<< "$body" >/dev/null; then found=true; break; fi
  sleep 2
done
rc=0; [[ "$found" == true ]] || rc=1
result "$rc" 'Slides trail includes Gateway model call and worker result' 'inspect audit writer and Kafka'
rc=0
request admin GET "$admin_base/api/admin/overview" && [[ "$status" == 200 ]] && jq -e '.cost_today_usd | type == "number"' <<< "$body" >/dev/null || rc=1
result "$rc" 'Overview cost is a number' 'inspect cost meter and Control Centre audiences'
rc=0
request ooh-harness-api POST http://127.0.0.1:18082/v1/classify "$(jq -cn --arg user "$check_user" '{text:"This is a connection test.",questions:{test:"Is this a connection test?"},user_id:$user}')" && [[ "$status" == 200 ]] && jq -e '.scores.test | type == "number" and . >= 0 and . <= 1' <<< "$body" >/dev/null || rc=1
reason='inspect classifier entry, Gateway and caller audience'
if [[ "$status" == 404 ]]; then reason='no classification model: add one in Models & tiers'; fi
result "$rc" 'classifier returns a score' "$reason"
# Synthetic content only; no real person's details.
safety_id="$(cat /proc/sys/kernel/random/uuid)"
safety_event="$(jq -cn --arg id "$safety_id" --arg user "$check_user" --arg conversation "$(cat /proc/sys/kernel/random/uuid)" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{event_id:$id,type:"chat.message",version:1,occurred_at:$at,correlation_id:$id,user_id:$user,producer:"stage-check",payload:{conversation_id:$conversation,message_id:$id,role:"user",text:"Fictional test record: phone +1-202-555-0147, ID TEST-000000. These are made-up details.",tier:1,model_title:null}}')"
rc=0
kafka write chat.messages "$safety_event" "$safety_id" || rc=1
require "$rc" 'safety test message published' 'inspect Kafka ACLs'
found=false; deadline=$((SECONDS + 120)); safety_scores='{}'; safety_flagged=false
while ((SECONDS < deadline)); do
  if request admin GET "$admin_base/api/admin/trail?correlation_id=$safety_id&limit=200" && [[ "$status" == 200 ]] && jq -e 'any(.[]; .action == "safety.classify" and (.scores | type == "object") and (.scores | length > 0))' <<< "$body" >/dev/null; then
    safety_scores="$(jq -c '[.[] | select(.action == "safety.classify")][0].scores' <<< "$body")"
    safety_flagged="$(jq -r '[.[] | select(.action == "safety.classify")][0].outcome == "flagged"' <<< "$body")"; found=true; break
  fi
  sleep 2
done
rc=0; [[ "$found" == true ]] || rc=1
result "$rc" 'safety classification scores in trail within 120 seconds' 'configure a classification model and inspect safety watcher'
if [[ "$found" == true ]]; then
  printf 'INFO safety scores %s\n' "$(jq -c 'with_entries(select(.key == "personal_data" or .key == "prompt_injection"))' <<< "$safety_scores")"
fi
# Clear only this run's flag. A low score is informative, not a failed check.
flag=''; deadline=$((SECONDS + 30))
while :; do
  if ! request admin GET "$admin_base/api/admin/approvals?status=pending&correlation_id=$safety_id&limit=200" || [[ "$status" != 200 ]]; then stop 'approvals could not be read'; fi
  flag="$(jq -r --arg id "$safety_id" '.[] | select(.correlation_id == $id and .action == "safety.flag") | .id' <<< "$body")"
  [[ -z "$flag" && "$safety_flagged" == true && "$SECONDS" -lt "$deadline" ]] || break
  sleep 2
done
if [[ -n "$flag" ]]; then
  rc=0
  request admin POST "$admin_base/api/admin/approvals/$flag/decision" '{"approved":false,"note":"stage check"}' && [[ "$status" == 200 ]] || rc=1
  result "$rc" 'test safety flag cleared' 'clear this test flag in Approvals'
else printf 'INFO safety score did not create a pending flag\n'; fi
entries='[]'; after=''
while :; do
  if ! request admin GET "$admin_base/api/admin/models?limit=200$after" || [[ "$status" != 200 ]]; then stop 'model entries could not be read'; fi
  jq -e 'type == "array"' <<< "$body" >/dev/null || stop 'model entries response is invalid'
  entries="$(jq -cn --argjson old "$entries" --argjson page "$body" '$old + [$page[] | select(.purpose == "chat" and .deleted_at == null and .has_key == true)]')"
  [[ "$(jq length <<< "$body")" == 200 ]] || break
  cursor="$(jq -er '.[-1].model_entry_id' <<< "$body")"
  [[ "$after" != "&after=$cursor" ]] || stop 'model paging did not advance'
  after="&after=$cursor"
done
[[ "$(jq length <<< "$entries")" != 0 ]] || stop 'no chat model with a saved key; add one in Models & tiers'
while IFS= read -r entry <&3; do
  id="$(jq -r '.model_entry_id' <<< "$entry")"
  # Display only bounded titles, never endpoint settings or provider responses.
  title="$(jq -r '.title | gsub("[\\r\\n\\t]"; " ") | .[0:100]' <<< "$entry")"
  tier="$(jq -r '.tier' <<< "$entry")"
  payload="$(jq -cn --arg id "$id" --arg user "$check_user" --argjson tier "$tier" '{purpose:"chat",tier:$tier,user_id:$user,model_entry_id:$id,stream:false,thinking:true,messages:[{role:"user",content:"Call the check_tool tool with value OK. This is a tool connection test."}],tools:[{name:"check_tool",description:"Return the supplied test value",input_schema:{type:"object",properties:{value:{type:"string"}},required:["value"],additionalProperties:false}}],tool_choice:{name:"check_tool"}}')"
  rc=0
  request ooh-harness-api POST http://127.0.0.1:18082/v1/call "$payload" && [[ "$status" == 200 ]] || rc=1
  if ((rc == 0)) && jq -e '.tool_choice_applied == false and (.tool_calls | length == 0)' <<< "$body" >/dev/null; then
    request ooh-harness-api POST http://127.0.0.1:18082/v1/call "$payload" && [[ "$status" == 200 ]] || rc=1
    if ((rc == 0)) && jq -e '.tool_calls | length == 0' <<< "$body" >/dev/null; then
      result 1 "$title" 'model did not call the tool with thinking on (auto)'; continue
    fi
  fi
  jq -e --arg id "$id" '.model_entry_id == $id and (.tool_calls | length == 1) and .tool_calls[0].name == "check_tool" and has("reasoning_state") and (.reasoning_state == null or (.reasoning_state | type == "object"))' <<< "$body" >/dev/null 2>&1 || rc=1
  if ((rc != 0)); then result 1 "$title tool call" 'inspect tool support, rate limit and budget'; continue; fi
  answer="$body"
  follow="$(printf '%s\n%s\n' "$payload" "$answer" | jq -sc '.[0] as $request | .[1] as $answer | $request | .tool_choice = "none" | .messages += [{role:"assistant",content:$answer.content,tool_calls:$answer.tool_calls,reasoning_state:$answer.reasoning_state},{role:"tool",tool_call_id:$answer.tool_calls[0].id,content:"OK"}]')"
  rc=0
  request ooh-harness-api POST http://127.0.0.1:18082/v1/call "$follow" && [[ "$status" == 200 ]] && jq -e '(.content | type == "string" and length > 0) and (.tool_calls | length == 0)' <<< "$body" >/dev/null || rc=1
  result "$rc" "$title tool result and reasoning round" 'inspect adapter reasoning history; the response must contain text'
  if ((rc == 0)); then
    third="$(printf '%s\n%s\n' "$follow" "$body" | jq -sc '.[0] as $follow | .[1] as $answer | $follow | .messages += [{role:"assistant",content:$answer.content,reasoning_state:$answer.reasoning_state},{role:"user",content:"What test value did the tool return earlier? Answer briefly."}]')"
    rc=0
    request ooh-harness-api POST http://127.0.0.1:18082/v1/call "$third" && [[ "$status" == 200 ]] && jq -e '.content | type == "string" and length > 0' <<< "$body" >/dev/null || rc=1
    result "$rc" "$title new question with earlier tool turn in history" 'inspect adapter handling of reasoning across turns'
  fi
  unset answer body payload follow third
# One representative per connection type; registry values stay in memory only.
done 3< <(jq -c 'sort_by(.api_type) | group_by(.api_type) | .[] | first' <<< "$entries")
rc=0
unknown_job="$(cat /proc/sys/kernel/random/uuid)"
request check GET "$harness_base/api/jobs/$unknown_job/file" && [[ "$status" == 404 ]] || rc=1
result "$rc" 'unknown job download refused' 'expected 404; inspect Harness ownership checks'
rc=0
request check GET "$harness_base/api/jobs/not-a-uuid/file" && [[ "$status" == 400 || "$status" == 404 ]] || rc=1
result "$rc" 'malformed job download refused' 'expected 400 or 404'
# A direct Kafka job has no Harness job row. Choose a real other-user job through
# harness_app instead; only the UUID leaves the read-only database check pod.
role_secret="$(kubectl -n "$PLATFORM_NAMESPACE" get databaseroles -o json | jq -er '[.items[] | select(.spec.name == "harness_app")] | if length == 1 then .[0].spec.passwordSecret.name else error("missing app role") end')" || stop 'Harness app database role unavailable'
check_token="$(stage_check_token ooh-harness-api)" || stop 'check token unavailable'
check_sub="$(printf '%s' "$check_token" | jq -Rr 'split(".")[1] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson | .sub')"
unset check_token
db_env="$(jq -cn --arg secret "$role_secret" --arg sub "$check_sub" '[{name:"PGPASSWORD",valueFrom:{secretKeyRef:{name:$secret,key:"password"}}},{name:"PGSSLMODE",value:"require"},{name:"CHECK_SUB",value:$sub}]')"
# shellcheck disable=SC2016 # Password expands only inside the pod through the Secret environment.
db_script='set -eu
set +x
printf "SELECT id FROM jobs WHERE user_id <> '\''%s'\'' AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1;\n" "$CHECK_SUB" | psql -X -h ooh-pg-rw -U harness_app -d harness -At -v ON_ERROR_STOP=1 2>/dev/null'
rc=0
run_pod "$PLATFORM_NAMESPACE" ghcr.io/cloudnative-pg/postgresql:18.4-system-trixie "$db_script" "$db_env" || rc=1
require "$rc" 'read one other-user job ID as harness_app' 'inspect Harness database app role and jobs migration'
other_job="$pod_output"
if [[ -z "$other_job" ]]; then printf "SKIP no other user's job yet\n"; else
  [[ "$other_job" =~ ^[a-f0-9-]{36}$ ]] || stop 'unexpected job ID from database'
  rc=0
  request check GET "$harness_base/api/jobs/$other_job/file" && [[ "$status" == 404 ]] || rc=1
  result "$rc" 'another user job download refused' 'expected 404; inspect Harness ownership checks'
fi
rc=0
request admin GET "$admin_base/api/admin/health" && [[ "$status" == 200 ]] && jq -e '
  ([.[].name] | sort) == (["harness-api","model-gateway","slides-worker","audit-writer","cost-meter","safety-watcher","kafka","keycloak"] | sort) and all(.[]; .status == "ok")' <<< "$body" >/dev/null || rc=1
result "$rc" 'every service health OK' 'inspect the down service and retry after the next health refresh'
# Routing uses only temporary grants for the check service account. Existing
# grants (including Everyone) are never removed to make a check pass.
route_grant() {
  local tier="$1"
  request admin POST "$admin_base/api/admin/grants" "$(jq -cn --arg user "$check_sub" --arg tier "$tier" '{right_key:("chat.tier."+$tier),subject_type:"user",subject_id:$user}')" || return 1
  [[ "$status" == 200 || "$status" == 201 ]] || return 1
  if [[ "$status" == 201 ]]; then routing_grants+=("$(jq -er '.id' <<< "$body")"); fi
}
route_question() {
  local question="$1" expected="$2" needs_note="$3" conversation completed
  request check POST "$harness_base/api/conversations" '{}' && [[ "$status" == 201 ]] || return 1
  conversation="$(jq -er '.id' <<< "$body")" || return 1
  request check POST "$harness_base/api/conversations/$conversation/messages" "$(jq -cn --arg text "$question" '{content:$text,tier:"auto"}')" && [[ "$status" == 200 ]] || return 1
  completed="$(python3 -c '
import json, sys
try:
    events = [json.loads(line[6:]) for line in sys.stdin if line.startswith("data: ")]
    assert not any(event["type"] == "failed" for event in events)
    completed = [event for event in events if event["type"] == "completed"]
    assert len(completed) == 1
    print(json.dumps(completed[0]))
except Exception:
    raise SystemExit(1) from None
' <<< "$body")" || return 1
  jq -e --argjson tier "$expected" --argjson note "$needs_note" '
    .tier == $tier and .routing.tier == $tier and
    (.routing.scores.needs_tier2 | type == "number") and
    (if $note then .routing.note == "This question may need tier 2. An admin can give you tier 2."
     else ((.routing.note // "") | startswith("Routing is unavailable") | not) end)' <<< "$completed" >/dev/null || return 1
  request check GET "$harness_base/api/conversations/$conversation" && [[ "$status" == 200 ]] || return 1
  jq -e --argjson routing "$(jq -c '.routing' <<< "$completed")" '[.messages[] | select(.role == "assistant")][-1].routing == $routing' <<< "$body" >/dev/null
}
rc=0
route_grant 1 || rc=1
require "$rc" 'routing check user has a tier 1 grant' 'configure an active tier 1 model and inspect Control Centre grants'
if ! request check GET "$harness_base/api/me" || [[ "$status" != 200 ]] || ! jq -e '.chat_tiers == [1]' <<< "$body" >/dev/null; then
  stop 'routing check needs only tier 1; remove broader check-user or Everyone grants in People & rights before retrying'
fi
simple_question='What is two plus two? Answer briefly.'
hard_question='Prove that every finite integral domain is a field. Give a rigorous proof using injectivity and surjectivity, and explain why finiteness is essential.'
rc=0
route_question "$simple_question" 1 false || rc=1
result "$rc" 'Auto simple question uses tier 1 with only tier 1 granted' 'inspect routing settings, classifier scores and tier 1 model'
rc=0
route_question "$hard_question" 1 true || rc=1
result "$rc" 'Auto hard question stays on tier 1 with the access note' 'inspect classifier threshold and fail-closed tier rights'
rc=0
route_grant 2 || rc=1
require "$rc" 'routing check user temporarily granted tier 2' 'configure an active tier 2 model and inspect Control Centre grants'
rc=0
route_question "$simple_question" 1 false || rc=1
result "$rc" 'Auto simple question stays on tier 1 with tier 2 granted' 'inspect classifier scores and routing threshold'
rc=0
route_question "$hard_question" 2 false || rc=1
result "$rc" 'Auto hard question uses tier 2 when granted' 'inspect classifier scores, routing threshold and tier 2 model'
rc=0
remove_routing_grants || rc=1
require "$rc" 'temporary routing grants removed' 'remove only the temporary check-user grants from this run in People & rights'
stage_check_end || stop 'check client did not disable'
((failed == 0)) || stop 'Stage 3 checks failed; fix every FAIL line and retry'
printf 'DONE\n'
