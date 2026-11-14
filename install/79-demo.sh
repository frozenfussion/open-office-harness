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
config = {'bootstrap.servers':os.environ['BOOTSTRAP'], 'security.protocol':'SASL_PLAINTEXT', 'sasl.mechanism':'SCRAM-SHA-512', 'sasl.username':'ooh-stage-check', 'sasl.password':os.environ.pop('PASSWORD')}
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
        print(json.dumps({'event_id':found['event_id'], 'file_key':found['payload'].get('output',{}).get('file_key') if found['payload'].get('output') else None}))
except Exception:
    raise SystemExit('Kafka check failed') from None
PY
POD
)"
  run_pod "$PLATFORM_NAMESPACE" "$script" "$env"
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
    print(json.dumps({'mtime':path.stat().st_mtime_ns}))
except Exception:
    raise SystemExit('file check failed') from None
PY
POD
)"
  run_pod "$APPS_NAMESPACE" "$script" "$env" true
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

pause() { printf '%s\n' "$1"; read -r -p 'Press Enter when ready: ' _ || stop 'input closed; demo stopped safely'; }
if [[ $# == 1 && "$1" == restore ]]; then
  for name in model-gateway slides-worker; do
    count="$(python3 -c 'import re,sys; s=open(sys.argv[1]).read(); print(re.search(r"^  replicas: ([0-9]+)$",s,re.M)[1])' "deploy/apps/$name/deployment.yaml")"
    kubectl -n "$APPS_NAMESPACE" scale "deployment/$name" --replicas="$count" >/dev/null
    kubectl -n "$APPS_NAMESPACE" rollout status "deployment/$name" --timeout=300s
  done
  printf 'DONE\n'; exit 0
fi
[[ $# == 2 || ( $# == 3 && "$3" == --auto && "$1" == dead-letter ) ]] || stop 'usage: install/79-demo.sh <worker-down|duplicate|dead-letter> <12-character image tag> [--auto]; or install/79-demo.sh restore'
mode="$1"; tag="$2"; auto="${3:-}"
[[ "$tag" =~ ^[a-f0-9]{12}$ && "$mode" =~ ^(worker-down|duplicate|dead-letter)$ ]] || stop 'invalid demo or image tag; see README'
slides_image="ghcr.io/frozenfussion/ooh-slides-worker:$tag"
if [[ "$mode" == worker-down ]]; then
  worker_replicas="$(record_count slides-worker)"
  kubectl -n "$APPS_NAMESPACE" scale deployment/slides-worker --replicas=0 >/dev/null
  kubectl -n "$APPS_NAMESPACE" wait --for=delete pod -l app=slides-worker --timeout=120s >/dev/null
  printf 'slides-worker pods: %s\n' "$(kubectl -n "$APPS_NAMESPACE" get pods -l app=slides-worker -o json | jq '.items | length')"
  pause 'Now ask for slides in the Workspace. The chat answers and the card stays Queued. Show the audience that chat still works.'
  restore_recorded || stop 'worker could not be restored; run install/79-demo.sh restore'
  pause 'The worker is back. Wait for the card to turn Ready, then download the file.'
elif [[ "$mode" == duplicate ]]; then
  stage_check_begin || stop 'temporary check client could not start'
  slide_topic='The water cycle'; make_event
  printf 'Sending one Slides request. Watch the first result complete.\n'
  kafka write skill.requests.slides "$slide_event" || stop 'Slides request could not be published'
  kafka read skill.results || stop 'first Slides result did not complete'
  result_id="$(jq -er '.event_id' <<< "$pod_output")"; file_key="$(jq -er '.file_key' <<< "$pod_output")"
  file_check || stop 'first PowerPoint file is missing or invalid'
  first_file="$pod_output"
  pause 'The first file is ready. Next the exact same message will be sent again; it must reuse the result and file.'
  kafka repeat skill.results "$slide_event" || stop 'duplicate result ID differs or no fresh result arrived'
  file_check && [[ "$pod_output" == "$first_file" ]] || stop 'duplicate changed the file modification time'
  printf 'PASS one result ID: %s\n' "$result_id"
  printf 'PASS unchanged file modification time: %s\n' "$(jq -r '.mtime' <<< "$pod_output")"
else
  printf 'WARNING Chat is unavailable while the Gateway is down. This demo makes paid calls after recovery. Ctrl+C restores both services.\n'
  pause 'Open Workspace and the Admin Console Failed messages screen. Start when the audience is ready.'
  stage_check_begin || stop 'temporary check client could not start'
  worker_replicas="$(record_count slides-worker)"
  gateway_replicas="$(record_count model-gateway)"
  kubectl -n "$APPS_NAMESPACE" scale deployment/slides-worker --replicas=0 >/dev/null
  kubectl -n "$APPS_NAMESPACE" wait --for=delete pod -l app=slides-worker --timeout=120s >/dev/null
  pause 'Now ask for slides in the Workspace. Wait for the chat to finish and the card to show Queued.'
  kubectl -n "$APPS_NAMESPACE" scale deployment/model-gateway --replicas=0 >/dev/null
  failed_since="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
  kubectl -n "$APPS_NAMESPACE" wait --for=delete pod -l app=model-gateway --timeout=120s >/dev/null
  kubectl -n "$APPS_NAMESPACE" scale deployment/slides-worker --replicas="$worker_replicas" >/dev/null
  kubectl -n "$APPS_NAMESPACE" rollout status deployment/slides-worker --timeout=300s >/dev/null
  printf 'The worker retries with the Gateway down. Watch Queued turn to Failed and a dead letter appear.\n'
  if [[ "$auto" == --auto ]]; then
    find_dead_letter "$failed_since"
    dead_id="$(jq -er '.id' <<< "$dead_letter")"
  else
    pause 'Wait for the card to show Failed and the worker_gave_up dead letter in Failed messages. The next step restores chat.'
  fi
  restore_recorded || stop 'services could not be restored; run install/79-demo.sh restore'
  if [[ "$auto" == --auto ]]; then
    replay "$dead_id" || stop 'automatic replay did not return 202 sent'
    printf 'PASS newest worker_gave_up dead letter replayed\n'
    job_id="$(jq -er '.correlation_id' <<< "$dead_letter")"
    kafka read skill.results || stop 'replayed Slides result did not complete within 180 seconds'
    file_key="$(jq -er '.file_key' <<< "$pod_output")"
    file_check || stop 'replayed PowerPoint file is missing or invalid'
    pause 'The replay completed and its file exists. Show the Workspace card turning Ready and download it.'
  else
    pause 'Chat is back. In Failed messages open the matching dead letter, click Replay and confirm. Wait for the Workspace card to turn Ready and download it.'
  fi
fi
restore_recorded || stop 'services could not be restored; run install/79-demo.sh restore'
stage_check_end || stop 'check client did not disable'
printf 'DONE\n'
