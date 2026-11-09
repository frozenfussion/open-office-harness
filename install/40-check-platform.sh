#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "step failed; see README troubleshooting and re-run this script"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source deploy/values/do.env
[[ -f "$HOME/.config/ooh/do.env" ]] || stop "local settings missing; copy install/ooh.env.example as described in README"
# shellcheck source=/dev/null
source "$HOME/.config/ooh/do.env"
for setting in LETSENCRYPT_EMAIL SPACES_REGION SPACES_BUCKET; do
  [[ -n "${!setting:-}" ]] || stop "local setting $setting is empty; fill it in as described in README"
done
failed=0
result() {
  if [[ "$1" == 0 ]]; then printf 'PASS %s\n' "$2"; else printf 'FAIL %s: %s\n' "$2" "$3"; failed=1; fi
}
for namespace in ooh-platform cert-manager; do
  rc=0
  pods="$(kubectl -n "$namespace" get pods -o json 2>/dev/null)" || rc=1
  # Completed import/bootstrap jobs are not running pods.
  jq -e '[.items[] | select(.status.phase != "Succeeded")] | length > 0 and all(.[]; any(.status.conditions[]?; .type == "Ready" and .status == "True"))' <<< "$pods" >/dev/null 2>&1 || rc=1
  result "$rc" "pods $namespace" 'pods are not Ready; inspect pod status and logs'
done
for entry in 'ooh-platform auth' 'ooh-apps harness' 'ooh-apps admin'; do
  read -r namespace name <<< "$entry"
  rc=0
  cert="$(kubectl -n "$namespace" get certificate "$name-tls" -o json 2>/dev/null)" || rc=1
  jq -e '.spec.issuerRef.name == "letsencrypt-prod" and (.metadata.generation as $g | any(.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $g))' <<< "$cert" >/dev/null 2>&1 || rc=1
  result "$rc" "production certificate $name" 'certificate is not Ready with production issuer; inspect certificate events'
done
for url in "https://harness.$DOMAIN/" "https://harness.$DOMAIN/api/" "https://admin.$DOMAIN/" "https://admin.$DOMAIN/api/"; do
  status="$(curl --connect-timeout 10 --max-time 30 -sS -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  rc=0; [[ "$status" == 200 ]] || rc=1
  result "$rc" "HTTPS $url" 'expected HTTP 200 with trusted TLS; check ingress, certificate and deployment'
done
issuer="https://auth.$DOMAIN/realms/ooh"
rc=0
body="$(curl --connect-timeout 10 --max-time 30 -fsS "$issuer/.well-known/openid-configuration" 2>/dev/null)" || rc=1
jq -e --arg issuer "$issuer" '.issuer == $issuer' <<< "$body" >/dev/null 2>&1 || rc=1
result "$rc" 'OIDC issuer and trusted TLS' 'expected ooh issuer; check realm import, hostname and certificate'
for file in deploy/platform/kafka/topics/*.yaml; do
  name="$(basename "$file" .yaml)"
  resource="${name//./-}"
  case "$name" in
    ooh.smoke) partitions=1; retention=3600000 ;;
    dlq.*) partitions=1; retention=2592000000 ;;
    skill.*) partitions=3; retention=604800000 ;;
    *) partitions=3; retention=2592000000 ;;
  esac
  rc=0
  topic="$(kubectl -n ooh-platform get kafkatopic "$resource" -o json 2>/dev/null)" || rc=1
  jq -e --arg name "$name" --argjson p "$partitions" --argjson r "$retention" '.spec.topicName == $name and .spec.partitions == $p and .spec.replicas == 1 and .spec.config["retention.ms"] == $r and .spec.config["min.insync.replicas"] == 1 and (.metadata.generation as $g | .status.observedGeneration == $g) and any(.status.conditions[]?; .type == "Ready" and .status == "True")' <<< "$topic" >/dev/null 2>&1 || rc=1
  result "$rc" "topic $name" 'topic configuration or reconciliation differs; re-run platform apply and inspect KafkaTopic'
done
check_pod=''
cleanup() {
  if [[ -n "$check_pod" ]]; then kubectl -n ooh-platform delete pod "$check_pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
run_pod() {
  local image="$1" script="$2" env="$3" rc=0
  check_pod="ooh-check-$(date +%s)-$RANDOM"
  jq -n --arg name "$check_pod" --arg image "$image" --arg script "$script" --argjson env "$env" '{apiVersion:"v1",kind:"Pod",metadata:{name:$name,namespace:"ooh-platform"},spec:{restartPolicy:"Never",activeDeadlineSeconds:150,automountServiceAccountToken:false,securityContext:{runAsNonRoot:true,runAsUser:1001,runAsGroup:1001,fsGroup:1001,seccompProfile:{type:"RuntimeDefault"}},containers:[{name:"check",image:$image,command:["/bin/bash","-ec",$script],env:$env,resources:{requests:{cpu:"100m",memory:"128Mi"},limits:{cpu:"500m",memory:"512Mi"}},securityContext:{readOnlyRootFilesystem:true,allowPrivilegeEscalation:false,capabilities:{drop:["ALL"]}},volumeMounts:[{name:"tmp",mountPath:"/tmp"}]}],volumes:[{name:"tmp",emptyDir:{medium:"Memory",sizeLimit:"64Mi"}}]}}' | kubectl create -f - >/dev/null
  for ((attempt=0; attempt<90; attempt++)); do
    phase="$(kubectl -n ooh-platform get pod "$check_pod" -o jsonpath='{.status.phase}')"
    [[ "$phase" != Succeeded && "$phase" != Failed ]] || break
    sleep 2
  done
  [[ "$phase" == Succeeded ]] || rc=1
  cleanup
  check_pod=''
  return "$rc"
}
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
credentials="$(kubectl -n ooh-platform get secret spaces -o json)" || rc=1
access="$(jq -r '.data["access-key"] | @base64d' <<< "$credentials")"
secret="$(jq -r '.data["secret-key"] | @base64d' <<< "$credentials")"
[[ -n "$access" && -n "$secret" && "$access$secret" != *[\"\\\$'\r\n']* ]] || stop "Spaces keys are missing or invalid; check secret with the owner"
url="https://$SPACES_BUCKET.$SPACES_REGION.digitaloceanspaces.com/checks/platform-$(date +%s)-$RANDOM.txt"
message="open-office-harness platform check $(date -u +%FT%TZ)"
spaces_curl() {
  printf 'user = "%s:%s"\n' "$access" "$secret" | curl --config - --aws-sigv4 "aws:amz:$SPACES_REGION:s3" --connect-timeout 10 --max-time 30 -fsS "$@" "$url"
}
spaces_curl -X PUT --data-binary "$message" >/dev/null 2>&1 || rc=1
readback="$(spaces_curl 2>/dev/null)" || rc=1
[[ "$readback" == "$message" ]] || rc=1
unset credentials access secret
result "$rc" 'storage write/read under checks/' 'check Spaces bucket, region and key read/write permissions; check objects are retained'
((failed == 0)) || stop "platform checks failed; fix the FAIL lines above and re-run"
printf 'DONE\n'
