#!/usr/bin/env bash

set -Eeuo pipefail

image_reference=${1:-}
certificate_identity_regexp=${COSIGN_CERTIFICATE_IDENTITY_REGEXP:-}
certificate_oidc_issuer=${COSIGN_CERTIFICATE_OIDC_ISSUER:-https://token.actions.githubusercontent.com}
if [[ ! "$image_reference" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "usage: verify-image.sh registry/repository@sha256:DIGEST" >&2
  exit 2
fi
for command in cosign trivy; do
  command -v "$command" >/dev/null 2>&1 || { echo "$command is required" >&2; exit 2; }
done
if [[ -z "$certificate_identity_regexp" ]]; then
  echo "COSIGN_CERTIFICATE_IDENTITY_REGEXP is required" >&2
  exit 2
fi
cosign verify \
  --certificate-identity-regexp "$certificate_identity_regexp" \
  --certificate-oidc-issuer "$certificate_oidc_issuer" \
  "$image_reference" >/dev/null
cosign verify-attestation \
  --type cyclonedx \
  --certificate-identity-regexp "$certificate_identity_regexp" \
  --certificate-oidc-issuer "$certificate_oidc_issuer" \
  "$image_reference" >/dev/null
trivy image --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 "$image_reference"
printf 'verified signature, CycloneDX attestation, and vulnerability gate: %s\n' "$image_reference"
