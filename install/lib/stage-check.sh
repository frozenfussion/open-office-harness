#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
set +x

_stage_check_stop() { printf 'STOP: %s\n' "$*" >&2; return 1; }
_stage_check_admin() {
  # Bootstrap credentials and CLI tokens never leave the Keycloak pod.
  # shellcheck disable=SC2016
  kubectl -n "$PLATFORM_NAMESPACE" exec ooh-keycloak-0 -c keycloak -- sh -c '
    set -eu
    set +x
    umask 077
    directory="$(mktemp -d /tmp/ooh-check-cli.XXXXXXXX)"
    trap '\''rm -rf -- "$directory"'\'' EXIT
    /opt/keycloak/bin/kcadm.sh config credentials --config "$directory/config" --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
    /opt/keycloak/bin/kcadm.sh "$@" --config "$directory/config" 2>/dev/null
  ' -- "$@" 2>/dev/null
}
_stage_check_rotate() { _stage_check_admin create "clients/$STAGE_CHECK_ID/client-secret" -r ooh >/dev/null; }
stage_check_begin() {
  command -v flock >/dev/null || { _stage_check_stop 'missing flock; finish server setup'; return 1; }
  mkdir -p "$HOME/.config/ooh" || return 1
  STAGE_CHECK_LOCK="$HOME/.config/ooh/stage-check.lock"
  umask 077
  exec {STAGE_CHECK_FD}<>"$STAGE_CHECK_LOCK" || return 1
  if ! flock -n "$STAGE_CHECK_FD"; then
    exec {STAGE_CHECK_FD}>&-
    _stage_check_stop 'another check is running'; return 1
  fi
  local previous
  previous="$(cat "$STAGE_CHECK_LOCK")"
  if [[ "$previous" =~ ^[0-9]+$ ]] && kill -0 "$previous" 2>/dev/null; then
    flock -u "$STAGE_CHECK_FD"; exec {STAGE_CHECK_FD}>&-
    _stage_check_stop 'another check is running'; return 1
  fi
  printf '%s\n' "$$" > "$STAGE_CHECK_LOCK"
  STAGE_CHECK_ACTIVE=true
  if ! STAGE_CHECK_ID="$(_stage_check_admin get clients -r ooh -q clientId=ooh-stage-check --fields id,clientId | jq -er 'if length == 1 and .[0].clientId == "ooh-stage-check" then .[0].id else error("missing client") end' 2>/dev/null)"; then
    _stage_check_stop 'check client missing; re-run install/35-realm-sync.sh'; return 1
  fi
  [[ "$STAGE_CHECK_ID" =~ ^[a-fA-F0-9-]+$ ]] || { _stage_check_stop 'invalid check client ID'; return 1; }
  if ! _stage_check_rotate || ! _stage_check_admin update "clients/$STAGE_CHECK_ID" -r ooh -s enabled=true >/dev/null; then
    _stage_check_stop 'check client could not be enabled; inspect Keycloak privately'; return 1
  fi
}
stage_check_token() {
  local audience="${1:-}" secret reply token claims
  [[ "${STAGE_CHECK_ACTIVE:-false}" == true && -n "$audience" ]] || { _stage_check_stop 'check client is not active or audience missing'; return 1; }
  secret="$(_stage_check_admin get "clients/$STAGE_CHECK_ID/client-secret" -r ooh | jq -jer '.value | select(type == "string" and length > 0) | @uri' 2>/dev/null)" || { _stage_check_stop 'check client secret unavailable'; return 1; }
  reply="$(printf 'grant_type=client_credentials&client_id=ooh-stage-check&client_secret=%s' "$secret" |
    curl --connect-timeout 10 --max-time 30 -fsS -H 'Content-Type: application/x-www-form-urlencoded' --data-binary @- "https://auth.$DOMAIN/realms/ooh/protocol/openid-connect/token" 2>/dev/null)" || { _stage_check_stop 'check token request failed'; return 1; }
  token="$(jq -er '.access_token | select(type == "string" and test("^[A-Za-z0-9_.-]+$"))' <<< "$reply" 2>/dev/null)" || { _stage_check_stop 'check token unavailable'; return 1; }
  claims="$(printf '%s' "$token" | jq -R 'split(".")[1] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson' 2>/dev/null)" || return 1
  jq -e --arg audience "$audience" '(.aud | if type == "array" then . else [.] end) | index($audience) != null' <<< "$claims" >/dev/null || { _stage_check_stop "stage-check token lacks audience $audience"; return 1; }
  printf '%s' "$token"
}
stage_check_end() {
  [[ "${STAGE_CHECK_ACTIVE:-false}" == true ]] || return 0
  local client rc=0
  if [[ -z "${STAGE_CHECK_ID:-}" ]]; then
    STAGE_CHECK_ID="$(_stage_check_admin get clients -r ooh -q clientId=ooh-stage-check --fields id | jq -er 'if length == 1 then .[0].id else error("missing") end' 2>/dev/null)" || rc=1
  fi
  [[ -n "${STAGE_CHECK_ID:-}" ]] || rc=1
  if ((rc == 0)); then
    _stage_check_admin update "clients/$STAGE_CHECK_ID" -r ooh -s enabled=false >/dev/null || rc=1
    _stage_check_rotate || rc=1
    client="$(_stage_check_admin get "clients/$STAGE_CHECK_ID" -r ooh --fields enabled)" || rc=1
    jq -e '.enabled == false' <<< "${client:-}" >/dev/null 2>&1 || rc=1
  fi
  if ((rc == 0)); then printf 'PASS ooh-stage-check disabled\n'; else printf 'FAIL ooh-stage-check still enabled\n'; fi
  ((rc == 0)) || return "$rc"
  : > "$STAGE_CHECK_LOCK"
  flock -u "$STAGE_CHECK_FD"
  exec {STAGE_CHECK_FD}>&-
  STAGE_CHECK_ACTIVE=false
  return "$rc"
}
