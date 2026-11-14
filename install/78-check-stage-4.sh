#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# shellcheck disable=SC2015 # Any failed part of a chained check must stop it.
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
# shellcheck source=install/lib/stage-check.sh
source install/lib/stage-check.sh
for tool in kubectl curl jq flock python3; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
failed=0
result() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s\n' "$2"; failed=1; fi
}
require() { result "$@"; [[ "$1" == 0 ]] || stop "cannot continue after $2; see Stage 4 help in README"; }
tmp="$(mktemp -d)"
check_pod=''; check_namespace=''; grant_id=''
gateway_replicas=''; worker_replicas=''
restore_recorded() {
  local rc=0
  if [[ -n "$gateway_replicas" ]]; then
    if kubectl -n "$APPS_NAMESPACE" scale deployment/model-gateway --replicas="$gateway_replicas" >/dev/null &&
      kubectl -n "$APPS_NAMESPACE" rollout status deployment/model-gateway --timeout=300s >/dev/null; then gateway_replicas=''; else rc=1; fi
  fi
  if [[ -n "$worker_replicas" ]]; then
    if kubectl -n "$APPS_NAMESPACE" scale deployment/slides-worker --replicas="$worker_replicas" >/dev/null &&
      kubectl -n "$APPS_NAMESPACE" rollout status deployment/slides-worker --timeout=300s >/dev/null; then worker_replicas=''; else rc=1; fi
  fi
  return "$rc"
}
remove_grant() {
  [[ -n "$grant_id" ]] || return 0
  request admin DELETE "$admin_base/api/admin/grants/$grant_id" && [[ "$status" == 200 ]] || return 1
  grant_id=''
}
cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  restore_recorded || { printf 'STOP: could not restore Deployments; run install/79-demo.sh restore\n' >&2; rc=1; }
  [[ -z "$check_pod" ]] || kubectl -n "$check_namespace" delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || rc=1
  remove_grant || { printf 'STOP: remove this run\047s temporary check-user tier grant in People & rights\n' >&2; rc=1; }
  stage_check_end || rc=1
  rm -rf -- "$tmp"
  ooh_target_cleanup
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap 'stop "step failed; see Stage 4 help in README and retry"' ERR
admin_base="https://admin.$DOMAIN"
harness_base="https://harness.$DOMAIN"
uuid() { cat /proc/sys/kernel/random/uuid; }
record_count() {
  local count
  count="$(kubectl -n "$APPS_NAMESPACE" get deployment "$1" -o jsonpath='{.spec.replicas}')" || return 1
  [[ "$count" =~ ^[0-9]+$ && "$count" -gt 0 ]] || { printf 'STOP: %s is already stopped; run install/79-demo.sh restore\n' "$1" >&2; return 1; }
  printf '%s' "$count"
}
request() {
  local principal="$1" method="$2" url="$3" data="${4:-}" token reply
  case "$principal" in
    admin) token="$(stage_check_token ooh-control-centre)" || return 1 ;;
    check) token="$(stage_check_token ooh-harness-api)" || return 1 ;;
    *) return 1 ;;
  esac
  reply="$( {
    printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'header = "Content-Type: application/json"\n'
    [[ -z "$data" ]] || { printf 'data = '; printf '%s' "$data" | jq -Rs .; }
  } | curl --config - --connect-timeout 10 --max-time 930 -sS -X "$method" "$url" -w '\n%{http_code}' 2>/dev/null)" || return 1
  status="${reply##*$'\n'}"; body="${reply%$'\n'*}"
}
pod_json() {
  local marked
  marked="$(sed -n '/^OOH_RESULT /p' <<< "$pod_output")"
  if [[ -z "$marked" || "$marked" == *$'\n'* ]] ||
    ! jq -se 'length == 1 and (.[0] | type == "object")' <<< "${marked#OOH_RESULT }" >/dev/null 2>&1; then
    printf 'FAIL check pod result: expected exactly one OOH_RESULT JSON line\n' >&2
    return 1
  fi
  pod_output=${marked#OOH_RESULT }
}
run_pod() {
  local namespace="$1" script="$2" env="$3" files="${4:-false}" phase='' deadline rc=0
  check_namespace="$namespace"; check_pod="ooh-stage4-$(date +%s)-$RANDOM"
  jq -n --arg namespace "$namespace" --arg name "$check_pod" --arg image "$slides_image" --arg script "$script" --argjson env "$env" --argjson files "$files" '
    {apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:$namespace},spec:{restartPolicy:"Never",activeDeadlineSeconds:240,automountServiceAccountToken:false,
    securityContext:{runAsNonRoot:true,runAsUser:10001,runAsGroup:10001,fsGroup:10001,seccompProfile:{type:"RuntimeDefault"}},
    containers:[{name:"check",image:$image,command:["/bin/sh","-ec",$script],env:$env,
    resources:{requests:{cpu:"50m",memory:"96Mi"},limits:{cpu:"500m",memory:"512Mi"}},
    securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"tmp",mountPath:"/tmp"}]}],
    volumes:[{name:"tmp",emptyDir:{medium:"Memory",sizeLimit:"32Mi"}}]}} |
    if $files then .spec.volumes += [{name:"files",persistentVolumeClaim:{claimName:"ooh-files",readOnly:true}}] | .spec.containers[0].volumeMounts += [{name:"files",mountPath:"/files",readOnly:true}] else . end' |
    kubectl create -f - >/dev/null || return 1
  deadline=$((SECONDS + 250))
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
make_event() {
  job_id="$(uuid)"; event_id="$(uuid)"
  slide_event="$(jq -cn --arg event "$event_id" --arg correlation "$job_id" --arg topic "$slide_topic" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{event_id:$event,type:"skill.requested",version:1,occurred_at:$at,correlation_id:$correlation,user_id:("stage-check-"+$correlation),producer:"stage-check",payload:{skill:"slides",skill_version:"1.0.0",input:{topic:$topic}}}')"
}
kafka() {
  local mode="$1" topic="$2" message="${3:-}" expected="${4:-completed}" timeout="${5:-180}" env script
  env="$(jq -cn --arg mode "$mode" --arg topic "$topic" --arg message "$message" --arg correlation "$job_id" --arg expected "$expected" --arg timeout "$timeout" --arg traceparent "${traceparent:-}" --arg result "${result_id:-}" --arg bootstrap "ooh-kafka-kafka-bootstrap.$PLATFORM_NAMESPACE.svc:9092" '[{name:"PASSWORD",valueFrom:{secretKeyRef:{name:"ooh-stage-check",key:"password"}}},{name:"MODE",value:$mode},{name:"TOPIC",value:$topic},{name:"MESSAGE",value:$message},{name:"CORRELATION",value:$correlation},{name:"EXPECTED",value:$expected},{name:"TIMEOUT",value:$timeout},{name:"TRACEPARENT",value:$traceparent},{name:"RESULT_ID",value:$result},{name:"BOOTSTRAP",value:$bootstrap}]')"
  script="$(cat <<'POD'
python - <<'PY'
import json, os, time
from confluent_kafka import Consumer, Producer, TopicPartition
config = {'log_level': 0, 'bootstrap.servers':os.environ['BOOTSTRAP'], 'security.protocol':'SASL_PLAINTEXT', 'sasl.mechanism':'SCRAM-SHA-512', 'sasl.username':'ooh-stage-check', 'sasl.password':os.environ.pop('PASSWORD')}
try:
    mode = os.environ['MODE']
    topic = os.environ['TOPIC']
    consumer = None
    if mode != 'write':
        consumer = Consumer({**config, 'group.id':'ooh-stage-check', 'enable.auto.commit':False})
        metadata = consumer.list_topics(topic, timeout=20)
        partitions = []
        for partition in metadata.topics[topic].partitions:
            offset = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=20)[1] if mode == 'repeat' else 0
            partitions.append(TopicPartition(topic, partition, offset))
        consumer.assign(partitions)
    if mode in ('write', 'repeat'):
        producer = Producer(config)
        errors = []
        headers = [('traceparent',os.environ['TRACEPARENT'].encode())] if os.environ['TRACEPARENT'] else []
        producer.produce('skill.requests.slides' if mode == 'repeat' else topic, key=os.environ['CORRELATION'], value=os.environ['MESSAGE'], headers=headers, on_delivery=lambda error, message: errors.append(error) if error else None)
        assert producer.flush(30) == 0 and not errors
    if consumer is not None:
        deadline = time.monotonic() + int(os.environ['TIMEOUT'])
        found = None
        while time.monotonic() < deadline:
            message = consumer.poll(1)
            if message is None: continue
            if message.error(): raise RuntimeError('consume failed')
            value = json.loads(message.value())
            if value.get('correlation_id') == os.environ['CORRELATION'] and value.get('payload',{}).get('status') == os.environ['EXPECTED']:
                found = value; break
        consumer.close()
        assert found is not None and found['type'] == 'skill.result'
        if os.environ['EXPECTED'] == 'failed':
            assert found['payload']['error']['code'] == 'worker_gave_up'
        if mode == 'repeat':
            assert found['event_id'] == os.environ['RESULT_ID']
        print('OOH_RESULT ' + json.dumps({'event_id':found['event_id'], 'file_key':found['payload'].get('output',{}).get('file_key') if found['payload'].get('output') else None}))
except Exception:
    raise SystemExit('Kafka check failed') from None
PY
POD
)"
  run_pod "$PLATFORM_NAMESPACE" "$script" "$env" || return 1
  [[ "$mode" == write ]] || pod_json
}
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
    print('OOH_RESULT ' + json.dumps({'mtime':path.stat().st_mtime_ns}))
except Exception:
    raise SystemExit('file check failed') from None
PY
POD
)"
  run_pod "$APPS_NAMESPACE" "$script" "$env" true && pod_json
}
find_dead_letter() {
  local after="$1" correlation="${2:-}" deadline=$((SECONDS + 120))
  while ((SECONDS < deadline)); do
    if request admin GET "$admin_base/api/admin/dead-letters?topic=dlq.skill.requests.slides&limit=200" && [[ "$status" == 200 ]]; then
      dead_letter="$(python3 -c '
import json,sys
from datetime import datetime
at=datetime.fromisoformat(sys.argv[1]); correlation=sys.argv[2]
rows=[r for r in json.load(sys.stdin) if r["error_code"]=="worker_gave_up" and datetime.fromisoformat(r["received_at"])>at and (not correlation or r.get("correlation_id")==correlation)]
if rows: print(json.dumps(max(rows,key=lambda r:datetime.fromisoformat(r["received_at"]))))
' "$after" "$correlation" <<< "$body")"
      [[ -z "$dead_letter" ]] || return 0
    fi
    sleep 2
  done
  stop 'no dead letter arrived; is the worker running?'
}
replay() {
  local id="$1"
  request admin POST "$admin_base/api/admin/dead-letters/$id/replay" '{}' && [[ "$status" == 202 ]] && jq -e '.outcome == "sent" and .target_topic == "skill.requests.slides"' <<< "$body" >/dev/null
}

[[ $# == 1 && "$1" =~ ^[a-f0-9]{12}$ ]] || stop 'usage: install/78-check-stage-4.sh <12-character image tag>'
tag="$1"
slides_image="ghcr.io/frozenfussion/ooh-slides-worker:$tag"
printf 'INFO This check makes paid calls and briefly stops chat. Never run it during a class.\n'
rc=0
deployments="$(kubectl -n "$APPS_NAMESPACE" get deployments -o json)" || rc=1
jq -e --arg suffix ":$tag" '
  (.items | length >= 9) and all(.items[];
  .metadata.generation <= (.status.observedGeneration // 0) and (.spec.replicas // 1) > 0 and
  .status.updatedReplicas == .spec.replicas and .status.readyReplicas == .spec.replicas and .status.availableReplicas == .spec.replicas and
  all(.spec.template.spec.containers[], .spec.template.spec.initContainers[]?; .image | endswith($suffix)))' <<< "$deployments" >/dev/null || rc=1
jaeger="$(kubectl -n "$PLATFORM_NAMESPACE" get deployment jaeger -o json)" || rc=1
jq -e '.metadata.generation <= (.status.observedGeneration // 0) and .spec.replicas == 1 and .status.updatedReplicas == 1 and .status.readyReplicas == 1 and .status.availableReplicas == 1' <<< "$jaeger" >/dev/null || rc=1
require "$rc" 'all application images have the requested tag and are Ready; Jaeger Ready'
stage_check_begin || stop 'temporary check client could not start'
check_token="$(stage_check_token ooh-harness-api)"
check_sub="$(printf '%s' "$check_token" | jq -Rr 'split(".")[1] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson | .sub')"
unset check_token
request admin POST "$admin_base/api/admin/grants" "$(jq -cn --arg user "$check_sub" '{right_key:"chat.tier.1",subject_type:"user",subject_id:$user}')" || stop 'check-user tier grant failed'
[[ "$status" == 200 || "$status" == 201 ]] || stop 'check-user tier grant failed'
if [[ "$status" == 201 ]]; then grant_id="$(jq -er '.id' <<< "$body")"; fi
marker="oohcheck$(uuid | tr -d '-')"
question="Say OK briefly. $marker"
slide_topic="The water cycle $marker"
request check POST "$harness_base/api/conversations" '{}' && [[ "$status" == 201 ]] || stop 'check conversation could not be created'
conversation="$(jq -er '.id' <<< "$body")"
request check POST "$harness_base/api/conversations/$conversation/messages" "$(jq -cn --arg text "$question" '{content:$text,tier:1}')" && [[ "$status" == 200 ]] || stop 'chat stream failed'
python3 -c 'import json,sys; events=[json.loads(x[6:]) for x in sys.stdin if x.startswith("data: ")]; assert sum(x["type"]=="completed" for x in events)==1 and not any(x["type"]=="failed" for x in events)' <<< "$body" || stop 'chat stream did not complete'
# Spec-author clarification: the saved user message ID is the correlation ID.
request check GET "$harness_base/api/conversations/$conversation" && [[ "$status" == 200 ]] || stop 'saved chat could not be read'
chat_correlation="$(jq -er '[.messages[] | select(.role == "user")] | last | .id' <<< "$body")"
trace_id=''; deadline=$((SECONDS + 60))
while ((SECONDS < deadline)); do
  if request admin GET "$admin_base/api/admin/trail?correlation_id=$chat_correlation&limit=200" && [[ "$status" == 200 ]] &&
    jq -e 'length > 0 and all(.[]; .trace_id != null and (.trace_id | test("^[0-9a-f]{32}$")) and .trace_id != "00000000000000000000000000000000") and ([.[].trace_id] | unique | length == 1)' <<< "$body" >/dev/null; then
    trace_id="$(jq -r '.[0].trace_id' <<< "$body")"
    if request admin GET "$admin_base/api/admin/traces/$trace_id" && [[ "$status" == 200 ]] && python3 -c '
import json,sys
v=json.load(sys.stdin); spans=v["spans"]; by_id={s["span_id"]:s for s in spans}
assert {"harness-api","control-centre","model-gateway"} <= {s["service"] for s in spans}
def descendant(s):
    for _ in spans:
        s=by_id.get(s.get("parent_span_id"))
        if s is None: return False
        if s["service"]=="harness-api": return True
    return False
assert any(descendant(s) for s in spans if s["service"]=="model-gateway")
' <<< "$body"; then break; fi
  fi
  sleep 2
done
rc=0; ((SECONDS < deadline)) || rc=1
require "$rc" 'chat audit rows share one trace; Harness, Control Centre and descendant Gateway spans visible within 60 seconds'
chat_trace="$trace_id"
trace_id="$(uuid | tr -d '-')"; parent_span="$(uuid | tr -d '-' | cut -c 1-16)"
traceparent="00-$trace_id-$parent_span-01"
make_event
kafka write skill.requests.slides "$slide_event" || stop 'traced Slides request could not be published'
kafka read skill.results || stop 'traced Slides job did not complete within 180 seconds'
# Inspect the unfiltered Jaeger answer inside the pod; only check outcomes leave it.
raw_trace_check() {
  local env script
  env="$(jq -cn --arg chat "$chat_trace" --arg slides "$trace_id" --arg marker "$marker" --arg parent "$parent_span" '[{name:"CHAT_TRACE",value:$chat},{name:"SLIDES_TRACE",value:$slides},{name:"MARKER",value:$marker},{name:"PARENT_SPAN",value:$parent}]')"
  script="$(cat <<'POD'
python - <<'PY'
import json, os, time, urllib.request
hop_ok = True
private_ok = True
try:
    for name, required in [('CHAT_TRACE',{'harness-api','control-centre','model-gateway'}),('SLIDES_TRACE',{'slides-worker','model-gateway','audit-writer'})]:
        trace = os.environ[name]
        deadline = time.monotonic()+60
        raw = None
        rows = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen('http://jaeger:16686/api/v3/traces/'+trace, timeout=5) as response:
                    raw = response.read().decode()
                value = json.loads(raw)
                rows = [(r,s) for r in value['result']['resourceSpans'] for scope in r.get('scopeSpans',[]) for s in scope.get('spans',[])]
                services = {next(a['value']['stringValue'] for a in r['resource']['attributes'] if a['key']=='service.name') for r,s in rows}
                if required <= services:
                    break
            except Exception:
                rows = None
            time.sleep(2)
        if rows is None or raw is None:
            hop_ok = False
            private_ok = False
            continue
        hop_ok = hop_ok and required <= services and all(s['traceId'] == trace for r,s in rows)
        if name == 'SLIDES_TRACE':
            hop_ok = hop_ok and any(s.get('parentSpanId') == os.environ['PARENT_SPAN'] for r,s in rows)
        private_ok = private_ok and os.environ['MARKER'] not in raw
        private_ok = private_ok and all(key not in raw for key in ('url.full','user_agent.original','client.address'))
        private_ok = private_ok and all(not s.get('events') for r,s in rows) and 'exception' not in raw.lower()
except Exception:
    hop_ok = False
    private_ok = False
print('HOP=' + ('ok' if hop_ok else 'failed'), 'PRIVATE=' + ('ok' if private_ok else 'failed'))
PY
POD
)"
  run_pod "$PLATFORM_NAMESPACE" "$script" "$env"
}
hop_rc=1; private_rc=1
if raw_trace_check; then
  [[ " $pod_output " != *' HOP=ok '* ]] || hop_rc=0
  [[ " $pod_output " != *' PRIVATE=ok '* ]] || private_rc=0
fi
result "$hop_rc" 'traced Slides hop includes worker, Gateway and audit writer under the injected trace ID'
result "$private_rc" 'raw chat/Slides trace privacy: no question/topic or forbidden fields/events'
((hop_rc == 0 && private_rc == 0)) || stop 'trace hop or privacy check failed; see the FAIL lines above'
# This direct Kafka request deliberately has no Harness job row.
gateway_replicas="$(record_count model-gateway)"
kubectl -n "$APPS_NAMESPACE" scale deployment/model-gateway --replicas=0 >/dev/null
kubectl -n "$APPS_NAMESPACE" wait --for=delete pod -l app=model-gateway --timeout=120s >/dev/null
failed_since="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
unset traceparent
make_event
kafka write skill.requests.slides "$slide_event" || stop 'failure-demo request could not be published'
kafka read skill.results '' failed 120 || stop 'worker_gave_up result did not arrive within 120 seconds'
find_dead_letter "$failed_since" "$job_id"
dead_id="$(jq -er '.id' <<< "$dead_letter")"
result 0 'worker_gave_up result and dead letter arrived'
restore_recorded || stop 'Gateway could not be restored; run install/79-demo.sh restore'
replay "$dead_id" || stop 'replay did not return 202 sent'
result 0 'replay accepted with 202 sent'
kafka read skill.results || stop 'replayed job did not complete within 180 seconds'
file_key="$(jq -er '.file_key' <<< "$pod_output")"
file_check || stop 'replayed job file is missing or invalid'
result 0 'replayed correlation completed with a valid PowerPoint file'
request admin GET "$admin_base/api/admin/dead-letters?topic=dlq.skill.requests.slides&limit=200" && [[ "$status" == 200 ]] &&
  jq -e --arg id "$dead_id" 'any(.[]; .id == $id and .replay_count >= 1)' <<< "$body" >/dev/null || stop 'replay count missing'
result 0 'dead letter replay_count is at least one'
deadline=$((SECONDS + 60))
while ((SECONDS < deadline)); do
  if request admin GET "$admin_base/api/admin/trail?action=dead_letter.replayed&limit=200" && [[ "$status" == 200 ]] &&
    jq -e --arg id "$dead_id" 'any(.[]; .action == "dead_letter.replayed" and .target == $id)' <<< "$body" >/dev/null; then break; fi
  sleep 2
done
rc=0; ((SECONDS < deadline)) || rc=1
require "$rc" 'dead_letter.replayed audit row present'
request admin GET "$admin_base/api/admin/dead-letters?topic=dlq.skill.requests.slides&limit=200" && [[ "$status" == 200 ]] || stop 'dead letters could not be read'
bad_id="$(jq -r '[.[] | select(.original_message == "not json")][0].id // empty' <<< "$body")"
if [[ -z "$bad_id" ]]; then
  bad_since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  kafka write skill.requests.slides 'not json' || stop 'malformed check message could not be published'
  deadline=$((SECONDS + 60))
  while ((SECONDS < deadline)); do
    if request admin GET "$admin_base/api/admin/dead-letters?topic=dlq.skill.requests.slides&limit=200" && [[ "$status" == 200 ]]; then
      bad_id="$(python3 -c '
import json,sys
from datetime import datetime
at=datetime.fromisoformat(sys.argv[1])
rows=[r for r in json.load(sys.stdin) if r["original_message"]=="not json" and datetime.fromisoformat(r["received_at"])>=at]
if rows: print(rows[0]["id"])
' "$bad_since" <<< "$body")"
      [[ -z "$bad_id" ]] || break
    fi
    sleep 2
  done
fi
[[ -n "$bad_id" ]] || stop 'malformed check dead letter did not arrive'
request admin POST "$admin_base/api/admin/dead-letters/$bad_id/replay" '{}' && [[ "$status" == 409 ]] && jq -e '.code == "not_replayable"' <<< "$body" >/dev/null || stop 'non-JSON replay was not refused'
result 0 'non-JSON replay refused with 409 not_replayable'
remove_grant || stop 'temporary check-user tier grant could not be removed'
stage_check_end || stop 'check client did not disable'
((failed == 0)) || stop 'Stage 4 checks failed; see README'
printf 'DONE\n'
