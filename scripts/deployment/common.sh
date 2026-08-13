#!/usr/bin/env bash

set -Eeuo pipefail

deployment_log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

deployment_fail() {
  deployment_log "ERROR: $*" >&2
  return 1
}

validate_deployment_root() {
  local deployment_root=$1
  if [[ "${AIOPS_DEPLOYMENT_TEST_MODE:-0}" == 1 && \
      -n "${AIOPS_DEPLOYMENT_TEST_ROOT:-}" && \
      "$deployment_root" == "$AIOPS_DEPLOYMENT_TEST_ROOT" && \
      "$deployment_root" == /tmp/aiops-x-deployment-test-* ]]; then
    return 0
  fi
  case "$deployment_root" in
    /home/*/aiops-x | /srv/*/aiops-x | /opt/*/aiops-x) ;;
    *)
      deployment_fail \
        "deployment root must be an explicit /home/*/aiops-x, /srv/*/aiops-x, or /opt/*/aiops-x path"
      ;;
  esac
  case "$deployment_root" in
    *'/../'* | *'/./'* | *'/..' | *'/.' )
      deployment_fail "deployment root must not contain relative path segments"
      ;;
  esac
}

file_mode() {
  local target=$1
  if stat -c '%a' "$target" >/dev/null 2>&1; then
    stat -c '%a' "$target"
    return
  fi
  stat -f '%Lp' "$target"
}

environment_value() {
  local environment_file=$1
  local variable_name=$2
  local line value
  line=$(grep -m1 "^${variable_name}=" "$environment_file" || true)
  value=${line#*=}
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value=${value:1:${#value}-2}
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value=${value:1:${#value}-2}
  fi
  printf '%s\n' "$value"
}

validate_ipv4_address() {
  local address=$1
  local octet
  if [[ ! "$address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    deployment_fail "expected an IPv4 address"
  fi
  local old_ifs=$IFS
  IFS=.
  read -r -a octets <<<"$address"
  IFS=$old_ifs
  for octet in "${octets[@]}"; do
    if [[ "$octet" =~ ^0[0-9]+$ ]] || ((octet < 0 || octet > 255)); then
      deployment_fail "invalid IPv4 address"
    fi
  done
}

validate_release_id() {
  local release_id=$1
  if [[ ! "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
    deployment_fail "release ID must use UTC format YYYYMMDDTHHMMSSZ"
  fi
}

calculate_sha256() {
  local target=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target" | awk '{print $1}'
    return
  fi
  deployment_fail "sha256sum or shasum is required"
}

certificate_public_key_sha256() {
  local certificate_path=$1
  openssl x509 -in "$certificate_path" -pubkey -noout 2>/dev/null \
    | openssl pkey -pubin -outform DER 2>/dev/null \
    | openssl dgst -sha256 2>/dev/null \
    | awk '{print $NF}'
}

private_key_public_sha256() {
  local private_key_path=$1
  openssl pkey -in "$private_key_path" -pubout -outform DER 2>/dev/null \
    | openssl dgst -sha256 2>/dev/null \
    | awk '{print $NF}'
}

validate_agent_pki() {
  local pki_directory=$1
  local server_name=$2
  local required_files='agent-ca-key.pem agent-ca-cert.pem agent-server-key.pem agent-server-cert.pem agent-task-signing-key.pem agent-task-signing-cert.pem'
  local pki_file
  for pki_file in $required_files; do
    if [[ ! -s "$pki_directory/$pki_file" ]]; then
      deployment_fail "Agent PKI is missing $pki_file"
    fi
  done

  openssl verify \
    -CAfile "$pki_directory/agent-ca-cert.pem" \
    "$pki_directory/agent-server-cert.pem" >/dev/null
  openssl x509 -in "$pki_directory/agent-ca-cert.pem" -checkend 86400 -noout >/dev/null
  openssl x509 -in "$pki_directory/agent-server-cert.pem" -checkend 86400 -noout >/dev/null
  openssl x509 -in "$pki_directory/agent-task-signing-cert.pem" -checkend 86400 -noout \
    >/dev/null

  if [[ "$(certificate_public_key_sha256 "$pki_directory/agent-ca-cert.pem")" != \
      "$(private_key_public_sha256 "$pki_directory/agent-ca-key.pem")" ]]; then
    deployment_fail "Agent CA certificate and private key do not match"
  fi
  if [[ "$(certificate_public_key_sha256 "$pki_directory/agent-server-cert.pem")" != \
      "$(private_key_public_sha256 "$pki_directory/agent-server-key.pem")" ]]; then
    deployment_fail "Agent server certificate and private key do not match"
  fi
  if [[ "$(certificate_public_key_sha256 "$pki_directory/agent-task-signing-cert.pem")" != \
      "$(private_key_public_sha256 "$pki_directory/agent-task-signing-key.pem")" ]]; then
    deployment_fail "Agent task-signing certificate and private key do not match"
  fi

  if [[ "$server_name" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    openssl x509 -in "$pki_directory/agent-server-cert.pem" \
      -checkip "$server_name" -noout >/dev/null
  else
    openssl x509 -in "$pki_directory/agent-server-cert.pem" \
      -checkhost "$server_name" -noout >/dev/null
  fi
}

run_release_compose() {
  local release_directory=$1
  local deployment_root=$2
  shift 2
  AIOPS_PKI_DIR="$deployment_root/shared/pki" \
    AIOPS_ALERTMANAGER_TOKEN_FILE="$deployment_root/shared/alertmanager-webhook-token" \
    docker compose \
      --project-directory "$release_directory" \
      -f "$release_directory/compose.yaml" \
      --env-file "$deployment_root/shared/.env" \
      "$@"
}

resolve_current_release() {
  local deployment_root=$1
  local current_link="$deployment_root/current"
  if [[ ! -e "$current_link" && ! -L "$current_link" ]]; then
    return 0
  fi
  if [[ ! -L "$current_link" ]]; then
    deployment_fail "$current_link exists but is not a symbolic link"
  fi
  local resolved
  local canonical_root link_target resolved_parent
  canonical_root=$(cd "$deployment_root" && pwd -P)
  link_target=$(readlink "$current_link")
  if [[ "$link_target" == /* ]]; then
    resolved=$link_target
  else
    resolved="$deployment_root/$link_target"
  fi
  resolved_parent=$(cd "$(dirname "$resolved")" && pwd -P)
  resolved="$resolved_parent/$(basename "$resolved")"
  case "$resolved" in
    "$canonical_root"/releases/*) printf '%s\n' "$resolved" ;;
    *) deployment_fail "current release resolves outside $deployment_root/releases" ;;
  esac
}

atomic_release_link() {
  local deployment_root=$1
  local release_id=$2
  local candidate="$deployment_root/.current-$release_id"
  if [[ -e "$candidate" || -L "$candidate" ]]; then
    deployment_fail "temporary current link already exists: $candidate"
  fi
  ln -s "releases/$release_id" "$candidate"
  python3 - "$candidate" "$deployment_root/current" <<'PY'
import os
import sys

os.replace(sys.argv[1], sys.argv[2])
PY
}
