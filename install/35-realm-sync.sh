#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x
stop() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
trap 'stop "realm audience sync failed; inspect Keycloak readiness and bootstrap access, then re-run step 6"' ERR
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=/dev/null
source "$ROOT/deploy/values/do.env"
registration=on
if [[ $# != 0 ]]; then
  [[ $# == 2 ]] || stop "usage: install/35-realm-sync.sh [--registration off|on]"
  [[ "$1" == --registration && ( "$2" == off || "$2" == on ) ]] || stop "usage: install/35-realm-sync.sh [--registration off|on]"
  registration="$2"
fi
registration_allowed=true
[[ "$registration" != off ]] || registration_allowed=false
for tool in kubectl jq awk sed; do command -v "$tool" >/dev/null || stop "missing tool $tool; finish server setup"; done
redact_errors() {
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    printf '%s\n' "$line"
  done | sed -E \
    -e 's/[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+/[REDACTED TOKEN]/g' \
    -e 's/([Bb]earer)[[:space:]]+[^[:space:]",}]+/\1 [REDACTED]/g' \
    -e '/((access|refresh|id)[_-]?token|token|password|client[_-]?secret|secret|authorization|credentials?)[[:space:]"]*[:=]/I c\[redacted sensitive diagnostic line]' >&2
}
wait_keycloak() {
  local deadline=$((SECONDS + 600)) resources
  printf 'Waiting for Keycloak and its current pod revision to be Ready\n'
  while ((SECONDS < deadline)); do
    # Read fresh objects each time: a replaced pod can be Failed, terminating or temporarily absent.
    if resources="$(kubectl -n "$PLATFORM_NAMESPACE" --request-timeout=10s get keycloak/ooh-keycloak statefulset/ooh-keycloak pod/ooh-keycloak-0 --ignore-not-found -o json 2>/dev/null)" &&
      jq -e '
        ([.items[]? | select(.kind == "Keycloak")][0] // {}) as $cr |
        ([.items[]? | select(.kind == "StatefulSet")][0] // {}) as $sts |
        ([.items[]? | select(.kind == "Pod")][0] // {}) as $pod |
        ($cr.metadata.deletionTimestamp == null) and
        ($cr.metadata.generation != null) and
        ($cr.status.observedGeneration == $cr.metadata.generation) and
        any($cr.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $cr.metadata.generation) and
        ($sts.metadata.deletionTimestamp == null) and
        ($sts.metadata.generation != null) and
        (($sts.status.observedGeneration // 0) >= $sts.metadata.generation) and
        (($sts.status.updateRevision // "") != "") and
        ($sts.status.currentRevision == $sts.status.updateRevision) and
        ($sts.status.readyReplicas == $sts.spec.replicas) and
        ($sts.status.updatedReplicas == $sts.spec.replicas) and
        ($pod.metadata.deletionTimestamp == null) and
        ($pod.status.phase == "Running") and
        ($pod.metadata.labels["controller-revision-hash"] == $sts.status.updateRevision) and
        any($pod.status.conditions[]?; .type == "Ready" and .status == "True")
      ' <<< "$resources" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  stop "Keycloak rollout is not Ready on the current revision after 10 minutes; inspect the Keycloak CR, StatefulSet and pod, then re-run step 6"
}
wait_keycloak
# Read only the client IDs and included audiences from the controlled realm YAML format.
awk '/(^|[[:space:]])[&*][a-zA-Z0-9]/ {exit 1}' deploy/platform/keycloak/realm-ooh.yaml || stop "realm client format changed; expand YAML aliases before syncing"
rows="$(awk '
  $1 == "-" && $2 == "clientId:" {client=$3; print "CLIENT\t" client}
  $1 ~ /^included\.(client|custom)\.audience:$/ {print "AUDIENCE\t" client "\t" $2}
' deploy/platform/keycloak/realm-ooh.yaml)"
desired="$(jq -Rn '[inputs | split("\t")] | reduce .[] as $row ({}; if $row[0] == "CLIENT" then .[$row[1]] = [] else .[$row[1]] += [$row[2]] end)' <<< "$rows")"
jq -e 'keys | sort == (["ooh-workspace","ooh-admin-console","ooh-harness-api","ooh-control-centre","ooh-model-gateway"] | sort)' <<< "$desired" >/dev/null || stop "realm client format changed; check realm-ooh.yaml before syncing"
jq -e '.["ooh-control-centre"] == ["ooh-model-gateway"]' <<< "$desired" >/dev/null ||
  stop "realm client format changed; check realm-ooh.yaml before syncing"
config_dir=''
cleanup() {
  if [[ "$config_dir" =~ ^/tmp/ooh-realm-sync\.[a-zA-Z0-9]+$ ]]; then
    kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- rm -rf -- "$config_dir" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
config_dir="$(kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- /bin/bash -c 'umask 077; mktemp -d /tmp/ooh-realm-sync.XXXXXXXX')"
[[ "$config_dir" =~ ^/tmp/ooh-realm-sync\.[a-zA-Z0-9]+$ ]] || stop "could not create private Keycloak CLI settings directory"
config="$config_dir/kcadm.config"
# The quoted shell command expands credentials only inside the pod.
# shellcheck disable=SC2016 # Expansion is intentionally performed by the pod shell.
kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- sh -c '
  set -eu
  set +x
  umask 077
  if [ -z "${KC_BOOTSTRAP_ADMIN_USERNAME:-}" ] || [ -z "${KC_BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
    printf "%s\n" "Bootstrap admin environment is missing inside the Keycloak pod" >&2
    exit 1
  fi
  if error_text="$(/opt/keycloak/bin/kcadm.sh config credentials --config "$1" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" 2>&1 >/dev/null)"; then
    chmod 600 "$1"
  else
    status=$?
    # Redact exact credentials before any diagnostic can leave the pod.
    for value in "$KC_BOOTSTRAP_ADMIN_PASSWORD" "$KC_BOOTSTRAP_ADMIN_USERNAME"; do
      remaining="$error_text"
      error_text=""
      while :; do
        case "$remaining" in
          *"$value"*)
            error_text="$error_text${remaining%%"$value"*}[REDACTED]"
            remaining="${remaining#*"$value"}"
            ;;
          *) error_text="$error_text$remaining"; break ;;
        esac
      done
    done
    printf "%s\n" "$error_text" >&2
    exit "$status"
  fi
' -- "$config" 2> >(redact_errors) || stop "Keycloak CLI login failed; see the redacted error above, then re-run step 6"
kcadm() {
  local options=()
  case "$1" in create|update) options+=(-i) ;; esac
  kubectl -n "$PLATFORM_NAMESPACE" exec "${options[@]}" ooh-keycloak-0 -c keycloak -- /opt/keycloak/bin/kcadm.sh "$@" --config "$config" 2> >(redact_errors) || {
    local status=$?
    printf 'Keycloak CLI %s failed (exit %s)\n' "$1" "$status" >&2
    return "$status"
  }
}
# Keep other realm settings, profile attributes and unmanaged-attribute policy intact.
kcadm update realms/ooh -s "registrationAllowed=$registration_allowed" \
  -s registrationEmailAsUsername=true -s loginWithEmailAllowed=true \
  -s duplicateEmailsAllowed=false -s editUsernameAllowed=false -s verifyEmail=false \
  -s resetPasswordAllowed=false -s internationalizationEnabled=true \
  -s 'supportedLocales=["en"]' -s defaultLocale=en \
  -s 'passwordPolicy=length(12) and notUsername and notEmail and maxLength(128)' >/dev/null
realm_settings="$(kcadm get realms/ooh --fields registrationAllowed,registrationEmailAsUsername,loginWithEmailAllowed,duplicateEmailsAllowed,editUsernameAllowed,verifyEmail,resetPasswordAllowed,internationalizationEnabled,supportedLocales,defaultLocale,passwordPolicy)"
jq -e --argjson registration "$registration_allowed" '
  .registrationAllowed == $registration and .registrationEmailAsUsername == true and
  .loginWithEmailAllowed == true and .duplicateEmailsAllowed == false and
  .editUsernameAllowed == false and .verifyEmail == false and .resetPasswordAllowed == false and
  .internationalizationEnabled == true and .supportedLocales == ["en"] and .defaultLocale == "en" and
  .passwordPolicy == "length(12) and notUsername and notEmail and maxLength(128)"' <<< "$realm_settings" >/dev/null ||
  stop "registration settings could not be verified; inspect realm ooh and re-run realm sync"
profile_attributes='[
  {"name":"organisation","displayName":"Organisation or team","required":{"roles":["user"]},"permissions":{"view":["admin","user"],"edit":["admin","user"]},"validations":{"length":{"min":1,"max":100}}},
  {"name":"access_reason","displayName":"Why do you need access?","permissions":{"view":["admin","user"],"edit":["admin","user"]},"validations":{"length":{"min":0,"max":300}}}
]'
profile_before="$(kcadm get users/profile -r ooh)"
jq -e '.attributes | type == "array"' <<< "$profile_before" >/dev/null ||
  stop "user profile response is invalid; inspect realm ooh before retrying"
profile_expected="$(jq -c --argjson additions "$profile_attributes" '
  reduce $additions[] as $attribute (.;
    if any(.attributes[]; .name == $attribute.name) then
      .attributes |= map(if .name == $attribute.name then $attribute else . end)
    else .attributes += [$attribute] end)' <<< "$profile_before")"
printf '%s' "$profile_expected" | kcadm update users/profile -r ooh -n -f - >/dev/null
profile_after="$(kcadm get users/profile -r ooh)"
jq -e --argjson before "$profile_before" --argjson additions "$profile_attributes" '
  def managed: .name == "organisation" or .name == "access_reason";
  def normalized: {name,displayName,required,permissions,validations};
  ([.attributes[] | select(managed) | normalized] | sort_by(.name)) == ($additions | map(normalized) | sort_by(.name)) and
  ([.attributes[] | select(managed | not)] | sort_by(.name)) == ([$before.attributes[] | select(managed | not)] | sort_by(.name)) and
  del(.attributes) == ($before | del(.attributes))' <<< "$profile_after" >/dev/null ||
  stop "user profile could not be verified; inspect attributes and unmanaged policy before retrying"
unset profile_before profile_expected profile_after
for key in noAccount doRegister registerTitle; do
  text='Request access'
  [[ "$key" != noAccount ]] || text='Need access?'
  printf '%s' "$text" | kcadm update "realms/ooh/localization/en/$key" -n -h 'Content-Type=text/plain' -f - >/dev/null
done
texts="$(kcadm get realms/ooh/localization/en)"
jq -e '.noAccount == "Need access?" and .doRegister == "Request access" and .registerTitle == "Request access"' <<< "$texts" >/dev/null ||
  stop "registration texts could not be verified; inspect English realm texts and retry"
printf 'Registration %s; profile and English texts verified\n' "$registration"
attribute_mappers="$(jq -cn '["organisation","access_reason"] | map({name:.,protocol:"openid-connect",protocolMapper:"oidc-usermodel-attribute-mapper",consentRequired:false,config:{"user.attribute":.,"claim.name":.,"jsonType.label":"String","access.token.claim":"true","id.token.claim":"false","userinfo.token.claim":"false"}})')"
normalize_attributes() {
  jq -c '[.[] | select(.name == "organisation" or .name == "access_reason") |
    {name,protocol,protocolMapper,config:(.config | {"user.attribute","claim.name","jsonType.label","access.token.claim","id.token.claim","userinfo.token.claim"})}] | sort_by(.name)'
}
normalize_mappers() {
  # Keycloak may add defaults or express the audience in either supported config field.
  jq -c '[.[] | select(.protocolMapper == "oidc-audience-mapper") |
    {name,protocol,protocolMapper,
     audiences: ([.config["included.client.audience"], .config["included.custom.audience"]] | map(select(type == "string" and length > 0)) | unique),
     accessToken: ((.config["access.token.claim"] | tostring) == "true"),
     idToken: (((.config["id.token.claim"] // false) | tostring) == "true")}] | sort_by(.name)'
}
audience_names() {
  jq -c '[.[] | select(.protocolMapper == "oidc-audience-mapper") |
    .config["included.client.audience"], .config["included.custom.audience"]] |
    map(select(type == "string" and length > 0)) | unique'
}
print_audiences() {
  local label="$1" names="$2" display
  # Show configured Stage 0 audience names only, never arbitrary config values or token-like strings.
  display="$(jq -r 'if length == 0 then "(none)" else map(if test("^ooh-[a-z0-9-]{1,60}$") then . else "[non-name audience redacted]" end) | join(", ") end' <<< "$names")"
  printf '%s audiences for %s: %s\n' "$label" "$client" "$display" >&2
}
while IFS= read -r client; do
  representation="$(kcadm get clients -r ooh -q "clientId=$client" --fields id,clientId)"
  if [[ "$(jq 'length' <<< "$representation")" == 0 ]]; then
    stop "client $client is missing from realm ooh; realm sync cannot create clients; inspect the initial realm setup"
  fi
  id="$(jq -er --arg client "$client" 'if length == 1 and .[0].clientId == $client then .[0].id else error("client missing or ambiguous") end' <<< "$representation")"
  if [[ "$client" == ooh-workspace || "$client" == ooh-admin-console ]]; then
    client_config="$(kcadm get "clients/$id" -r ooh)"
    jq '.attributes = ((.attributes // {}) + {"post.logout.redirect.uris":"+"})' <<< "$client_config" |
      kcadm update "clients/$id" -r ooh -n -f - >/dev/null
    client_config="$(kcadm get "clients/$id" -r ooh)"
    jq -e '.attributes["post.logout.redirect.uris"] == "+"' <<< "$client_config" >/dev/null ||
      stop "sign-out redirect is not enabled for $client; inspect the existing client"
    unset client_config
  fi
  if [[ "$client" == ooh-admin-console ]]; then
    client_config="$(kcadm get "clients/$id" -r ooh)"
    printf '%s' "$client_config" | jq '.attributes = ((.attributes // {}) + {"oauth2.device.authorization.grant.enabled":"true"})' |
      kcadm update "clients/$id" -r ooh -n -f - >/dev/null
    client_config="$(kcadm get "clients/$id" -r ooh)"
    jq -e '.attributes["oauth2.device.authorization.grant.enabled"] == "true"' <<< "$client_config" >/dev/null ||
      stop "device sign-in is not enabled; inspect the existing admin console client"
    unset client_config
    printf 'Enabled device sign-in: ooh-admin-console\n'
  fi
  endpoint="clients/$id/protocol-mappers/models"
  existing="$(kcadm get "$endpoint" -r ooh)"
  audiences="$(jq -c --arg client "$client" '.[$client]' <<< "$desired")"
  expected="$(jq -cn --argjson audiences "$audiences" '$audiences | map({name:("audience-" + .),protocol:"openid-connect",protocolMapper:"oidc-audience-mapper",consentRequired:false,config:{"included.client.audience":.,"access.token.claim":"true","id.token.claim":"false"}})')"
  while IFS= read -r mapper; do
    name="$(jq -r '.name' <<< "$mapper")"
    matches="$(jq -c --arg name "$name" '[.[] | select(.name == $name)]' <<< "$existing")"
    count="$(jq 'length' <<< "$matches")"
    if [[ "$count" == 0 ]]; then
      printf '%s\n' "$mapper" | kcadm create "$endpoint" -r ooh -f - >/dev/null
    elif [[ "$count" == 1 ]]; then
      jq -e '.[0].protocolMapper == "oidc-audience-mapper"' <<< "$matches" >/dev/null || stop "mapper name conflicts with another mapper type for $client; inspect it before retrying"
      if [[ "$(normalize_mappers <<< "$matches")" != "$(normalize_mappers <<< "[$mapper]")" ]]; then
        mapper_id="$(jq -er '.[0].id' <<< "$matches")"
        update="$(jq -c --arg id "$mapper_id" '. + {id:$id}' <<< "$mapper")"
        printf '%s\n' "$update" | kcadm update "$endpoint/$mapper_id" -r ooh -n -f - >/dev/null
      fi
    else
      stop "duplicate mapper names for $client; inspect them before retrying"
    fi
  done < <(jq -c '.[]' <<< "$expected")
  # Only audience configuration is removed; unrelated mapper types are left untouched.
  while IFS= read -r mapper_id; do
    kcadm delete "$endpoint/$mapper_id" -r ooh >/dev/null
  done < <(jq -r --argjson expected "$expected" '.[] | select(.protocolMapper == "oidc-audience-mapper") | . as $mapper | select(all($expected[]; .name != $mapper.name)) | .id' <<< "$existing")
  if [[ "$client" == ooh-workspace ]]; then
    while IFS= read -r mapper; do
      name="$(jq -r '.name' <<< "$mapper")"
      matches="$(jq -c --arg name "$name" '[.[] | select(.name == $name)]' <<< "$existing")"
      count="$(jq length <<< "$matches")"
      if [[ "$count" == 0 ]]; then
        printf '%s' "$mapper" | kcadm create "$endpoint" -r ooh -f - >/dev/null
      elif [[ "$count" == 1 ]]; then
        jq -e '.[0].protocolMapper == "oidc-usermodel-attribute-mapper"' <<< "$matches" >/dev/null ||
          stop "mapper name conflicts with another mapper type for $client; inspect it before retrying"
        if [[ "$(normalize_attributes <<< "$matches")" != "$(normalize_attributes <<< "[$mapper]")" ]]; then
          mapper_id="$(jq -er '.[0].id' <<< "$matches")"
          jq --arg id "$mapper_id" '. + {id:$id}' <<< "$mapper" | kcadm update "$endpoint/$mapper_id" -r ooh -n -f - >/dev/null
        fi
      else
        stop "duplicate mapper names for $client; inspect them before retrying"
      fi
    done < <(jq -c '.[]' <<< "$attribute_mappers")
  fi
  actual="$(kcadm get "$endpoint" -r ooh)"
  if [[ "$client" == ooh-workspace && "$(normalize_attributes <<< "$actual")" != "$(normalize_attributes <<< "$attribute_mappers")" ]]; then
    stop "registration attribute mappers could not be verified; inspect the Workspace client and retry"
  fi
  if [[ "$(normalize_mappers <<< "$actual")" != "$(normalize_mappers <<< "$expected")" ]]; then
    found_names="$(audience_names <<< "$actual")"
    expected_names="$(audience_names <<< "$expected")"
    print_audiences FOUND "$found_names"
    print_audiences EXPECTED "$expected_names"
    if [[ "$found_names" == "$expected_names" ]]; then
      printf 'Audience values match, but mapper names, protocol or token flags differ\n' >&2
    fi
    stop "audience verification failed for $client; re-run step 6"
  fi
  printf 'Synced audience mappers: %s\n' "$client"
done < <(jq -r 'keys[]' <<< "$desired")
printf 'DONE\n'
