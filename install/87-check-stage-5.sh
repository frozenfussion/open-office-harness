#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# shellcheck disable=SC2015 # Every failed part of a compound check fails that check.
set -euo pipefail
set +x
umask 077
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ $# == 1 && "$1" =~ ^[a-f0-9]{12}$ ]] || stop 'usage: install/87-check-stage-5.sh <12-character image tag>'
tag="$1"
# shellcheck source=/dev/null
source "$ROOT/install/lib/target.sh"
# shellcheck source=install/lib/stage-check.sh
source install/lib/stage-check.sh
for tool in kubectl curl jq flock python3; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
require() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s\n' "$2"; stop 'Stage 5 check failed; see Stage 5 help in README'; fi
}
tmp="$(mktemp -d)"
grants=()
admin_base="https://admin.$DOMAIN"
harness_base="https://harness.$DOMAIN"
http() {
  local principal="$1" method="$2" url="$3" mime="${4:-application/json}" file="${5:-}" token
  case "$principal" in
    admin) token="$(stage_check_token ooh-control-centre)" || return 1 ;;
    check) token="$(stage_check_token ooh-harness-api)" || return 1 ;;
    *) return 1 ;;
  esac
  status="$( {
    printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'header = "Content-Type: %s"\n' "$mime"
    [[ "$mime" != image/png ]] || printf 'header = "X-File-Name: check-picture.png"\n'
    [[ -z "$file" ]] || printf 'data-binary = "@%s"\n' "$file"
  } | curl --config - --connect-timeout 10 --max-time 930 -sS -X "$method" "$url" -D "$tmp/headers" -o "$tmp/response" -w '%{http_code}' 2>/dev/null)" || return 1
  if [[ "$method" == POST && "$url" == "$harness_base/api/uploads" && "$status" == 429 ]] &&
    jq -e '.code == "upload_limit"' "$tmp/response" >/dev/null 2>&1; then
    printf 'FAIL daily picture limit reached for the check user, try after 08:00 Malaysia time\n'
    stop 'daily picture limit reached; see Stage 5 help in README'
  fi
}
request() {
  local file=''
  if [[ $# == 4 ]]; then printf '%s' "$4" > "$tmp/request"; file="$tmp/request"; fi
  http "$1" "$2" "$3" application/json "$file" || return 1
  body="$(cat "$tmp/response")"
}
remove_grants() {
  local id rc=0
  local remaining=()
  for id in "${grants[@]}"; do
    if ! request admin DELETE "$admin_base/api/admin/grants/$id" || [[ "$status" != 200 ]]; then remaining+=("$id"); rc=1; fi
  done
  grants=("${remaining[@]}")
  return "$rc"
}
cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  remove_grants || { printf 'STOP: temporary check-user grants could not be removed; inspect People & rights\n' >&2; rc=1; }
  stage_check_end || rc=1
  rm -rf -- "$tmp"
  ooh_target_cleanup
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap 'stop "Stage 5 step could not continue; see Stage 5 help in README"' ERR
run_start="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
rc=0
deployments="$(kubectl -n "$APPS_NAMESPACE" get deployments -o json)" || rc=1
jq -e --arg suffix ":$tag" '
  (.items | length >= 9) and all(.items[];
  .metadata.generation <= (.status.observedGeneration // 0) and (.spec.replicas // 1) > 0 and
  .status.updatedReplicas == .spec.replicas and .status.readyReplicas == .spec.replicas and .status.availableReplicas == .spec.replicas and
  all(.spec.template.spec.containers[], .spec.template.spec.initContainers[]?; .image | endswith($suffix)))' <<< "$deployments" >/dev/null || rc=1
require "$rc" 'every application Deployment has the requested image tag and is Ready'
stage_check_begin || stop 'temporary check client could not start'
check_token="$(stage_check_token ooh-harness-api)"
check_sub="$(printf '%s' "$check_token" | jq -Rr 'split(".")[1] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson | .sub')"
unset check_token
# A lossless 64 x 64 PNG, red on the left and blue on the right.
picture_base64='iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAA5ElEQVR4Ae3TsQ3AIAADQfZfmmSDK150ltK9FMMbn3vO0+/x7+/b0/9qdgG9D/Fa0RqQYfE1UA3IsHjN3wZkWHwNVAMyLF7ztwEZFl8D1YAMi9f8bUCGxddANSDD4jV/G5Bh8TVQDciweM3fBmRYfA1UAzIsXvO3ARkWXwPVgAyL1/xtQIbF10A1IMPiNX8bkGHxNVANyLB4zd8GZFh8DVQDMixe87cBGRZfA9WADIvX/G1AhsXXQDUgw+I1fxuQYfE1UA3IsHjN3wZkWHwNVAMyLF7ztwEZFl8D1YAMi9f81xv4ALjs8OIEgIHRAAAAAElFTkSuQmCC'
printf '%s' "$picture_base64" | python3 -c 'import base64,sys; open(sys.argv[1],"wb").write(base64.b64decode(sys.stdin.read(),validate=True))' "$tmp/picture.png"
upload() {
  http check POST "$harness_base/api/uploads" image/png "$tmp/picture.png" || return 1
  [[ "$status" == 201 ]] || return 1
  upload_id="$(jq -er '.upload_id | select(test("^[a-f0-9-]{36}$"))' "$tmp/response")" || return 1
}
rc=0
upload || rc=1
first_upload="${upload_id:-}"
if ((rc == 0)); then
  http check GET "$harness_base/api/uploads/$first_upload" || rc=1
  [[ "$status" == 200 ]] || rc=1
  python3 - "$tmp/picture.png" "$tmp/response" <<'PY' >/dev/null 2>&1 || rc=1
import hashlib, pathlib, sys
assert hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).digest() == hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).digest()
PY
fi
require "$rc" 'PNG upload returns 201 and its authenticated download has the same SHA-256'
entries='[]'; after=''
while :; do
  request admin GET "$admin_base/api/admin/models?limit=200$after" && [[ "$status" == 200 ]] || stop 'model entries could not be read'
  entries="$(jq -cn --argjson old "$entries" --argjson page "$body" '$old + [$page[] | select(.purpose == "chat" and .role == "main" and .deleted_at == null)]')"
  [[ "$(jq length <<< "$body")" == 200 ]] || break
  cursor="$(jq -er '.[-1].model_entry_id' <<< "$body")"
  [[ "$after" != "&after=$cursor" ]] || stop 'model paging did not advance'
  after="&after=$cursor"
done
tiers="$(jq -c '[.[].tier] | unique | sort' <<< "$entries")"
jq -e 'index(1) != null' <<< "$tiers" >/dev/null || stop 'no active main tier 1 model; configure Models & tiers'
question='What colour is the left half of this picture? Answer with one word.'
stream_colour() {
  python3 -c '
import json, sys
events=[json.loads(line[6:]) for line in sys.stdin if line.startswith("data: ")]
assert sum(e["type"]=="completed" for e in events)==1 and not any(e["type"]=="failed" for e in events)
answer="".join(e["text"] for e in events if e["type"]=="delta").lower()
assert sys.argv[1] in answer
if sys.argv[2]=="1": assert "blue" not in answer
' "$1" "${2:-0}" <<< "$body" >/dev/null 2>&1
}
while IFS= read -r tier; do
  request admin POST "$admin_base/api/admin/grants" "$(jq -cn --arg user "$check_sub" --arg tier "$tier" '{right_key:("chat.tier."+$tier),subject_type:"user",subject_id:$user}')" || stop 'check-user tier grant failed'
  [[ "$status" == 200 || "$status" == 201 ]] || stop 'check-user tier grant failed'
  if [[ "$status" == 201 ]]; then grants+=("$(jq -er '.id' <<< "$body")"); fi
  if [[ "$tier" == 1 ]]; then upload_id="$first_upload"; else upload || stop 'picture upload for chat tier failed'; fi
  request check POST "$harness_base/api/conversations" '{}' && [[ "$status" == 201 ]] || stop 'check conversation could not be created'
  conversation="$(jq -er '.id' <<< "$body")"
  if [[ "$tier" == 1 ]]; then tier_one_conversation="$conversation"; fi
  rc=0
  request check POST "$harness_base/api/conversations/$conversation/messages" "$(jq -cn --arg text "$question" --arg upload "$upload_id" --argjson tier "$tier" '{content:$text,tier:$tier,upload_id:$upload}')" && [[ "$status" == 200 ]] && stream_colour red "$tier" || rc=1
  require "$rc" "tier $tier completes a picture answer containing red; tier 1 does not say blue"
done < <(jq -r '.[]' <<< "$tiers")
rc=0
request check POST "$harness_base/api/conversations/$tier_one_conversation/messages" '{"content":"And the right half? One word.","tier":1}' && [[ "$status" == 200 ]] && stream_colour blue || rc=1
require "$rc" 'tier 1 follow-up without another attachment answers blue from the retained picture'
rc=0
printf 'not a picture' > "$tmp/invalid"
http check POST "$harness_base/api/uploads" image/png "$tmp/invalid" && [[ "$status" == 400 ]] && jq -e '.code == "unsupported_type"' "$tmp/response" >/dev/null || rc=1
require "$rc" 'text labelled image/png is refused with 400 unsupported_type'
request check GET "$harness_base/api/me" && [[ "$status" == 200 ]] || stop 'upload limit could not be read'
limit="$(jq -er '.upload_max_bytes | select(type == "number" and . >= 1048576 and . <= 7340032 and . == floor and . % 1048576 == 0)' <<< "$body" 2>/dev/null)" ||
  stop 'upload_max_bytes from /api/me is not a whole MB from 1 to 7; check HA_UPLOAD_MAX_BYTES'
python3 - "$tmp/oversize" "$limit" <<'PY'
import pathlib, sys
pathlib.Path(sys.argv[1]).write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(int(sys.argv[2]) + 1 - 8))
PY
rc=0
http check POST "$harness_base/api/uploads" image/png "$tmp/oversize" && [[ "$status" == 413 ]] && jq -e '.code == "too_large"' "$tmp/response" >/dev/null || rc=1
require "$rc" 'PNG signature and limit plus one byte is refused with Harness 413 too_large'
rc=0
unknown="$(cat /proc/sys/kernel/random/uuid)"
request check POST "$harness_base/api/conversations/$tier_one_conversation/messages" "$(jq -cn --arg upload "$unknown" '{content:"Check unknown picture",tier:1,upload_id:$upload}')" && [[ "$status" == 404 ]] && jq -e '.code == "upload_not_found"' <<< "$body" >/dev/null || rc=1
require "$rc" 'unknown picture is refused with 404 upload_not_found'
rc=0
request check POST "$harness_base/api/conversations/$tier_one_conversation/messages" "$(jq -cn --arg upload "$first_upload" '{content:"Check reused picture",tier:1,upload_id:$upload}')" && [[ "$status" == 409 ]] && jq -e '.code == "upload_used"' <<< "$body" >/dev/null || rc=1
require "$rc" 'already sent picture is refused with 409 upload_used'
rc=0
http check GET "$harness_base/api/conversations/$tier_one_conversation/export" && [[ "$status" == 200 ]] || rc=1
python3 - "$tmp/headers" "$tmp/response" "$question" <<'PY' >/dev/null 2>&1 || rc=1
import pathlib, re, sys, zipfile
from xml.etree import ElementTree as ET
headers = pathlib.Path(sys.argv[1]).read_text()
assert re.search(r'^content-type:\s*application/vnd.openxmlformats-officedocument.wordprocessingml.document\s*$', headers, re.I | re.M)
assert pathlib.Path(sys.argv[2]).read_bytes().startswith(b'PK')
with zipfile.ZipFile(sys.argv[2]) as archive:
    root = ET.fromstring(archive.read('word/document.xml'))
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
text = '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns))
assert sys.argv[3] in text and '[Picture attached:' in text
assert re.search(r'exported\s+\d{1,2} [A-Za-z]{3} \d{4} \d{2}:\d{2}\s*\(\+08\)', text)
PY
require "$rc" 'Word export has its MIME, ZIP bytes, question, picture label and exported time with +08'
deadline=$((SECONDS + 60)); audit_ok=1
while ((SECONDS < deadline)); do
  if request admin GET "$admin_base/api/admin/trail?actor=$check_sub&limit=200" && [[ "$status" == 200 ]] &&
    python3 -c '
import json, sys
from datetime import datetime
at=datetime.fromisoformat(sys.argv[1]); actor=sys.argv[2]; conversation=sys.argv[3]
rows=[r for r in json.load(sys.stdin) if r["actor"]==actor and datetime.fromisoformat(r["occurred_at"]) >= at and r["outcome"]=="ok"]
assert any(r["action"]=="upload.created" and r["target"]=="image/png" for r in rows)
assert any(r["action"]=="conversation.exported" and r["target"]=="docx" and r["correlation_id"]==conversation for r in rows)
' "$run_start" "$check_sub" "$tier_one_conversation" <<< "$body" >/dev/null 2>&1; then audit_ok=0; break; fi
  sleep 2
done
require "$audit_ok" 'upload.created and conversation.exported audit rows for this run arrive within 60 seconds'
rc=0
pods="$(kubectl -n "$APPS_NAMESPACE" get pods -o json)" || rc=1
slice="${picture_base64:$(( ${#picture_base64} / 2 )):40}"
while IFS= read -r pod; do
  logs="$(kubectl -n "$APPS_NAMESPACE" logs "$pod" --all-containers=true --since-time="$run_start" 2>/dev/null)" || rc=1
  [[ "$logs" != *"$slice"* ]] || rc=1
  unset logs
done < <(jq -r '.items[].metadata.name' <<< "$pods")
require "$rc" 'every application pod log since run start excludes the middle 40 characters of the picture data'
remove_grants || stop 'temporary check-user grants could not be removed; inspect People & rights'
stage_check_end || stop 'check client did not disable'
printf 'DONE\n'
