#!/usr/bin/env bash
# Apply Hasura metadata to the homelab Quran instance.
#
# Admin secret is pulled from the sops-encrypted secret in the sibling
# homelab repo so there is one source of truth. Requires: sops, yq, hasura.
#
# Usage: ./hasura/apply.sh [--dry-run]

set -euo pipefail

SECRETS_FILE="${SECRETS_FILE:-$(git rev-parse --show-toplevel)/../homelab/quran/secrets.sops.yaml}"
ENDPOINT="${HASURA_ENDPOINT:-http://quran.jawad}"

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "error: secrets file not found at $SECRETS_FILE" >&2
  echo "set SECRETS_FILE=/path/to/secrets.sops.yaml to override" >&2
  exit 1
fi

ADMIN_SECRET="$(sops -d "$SECRETS_FILE" | yq -r '.stringData.HASURA_GRAPHQL_ADMIN_SECRET')"

if [[ -z "$ADMIN_SECRET" || "$ADMIN_SECRET" == "null" ]]; then
  echo "error: HASURA_GRAPHQL_ADMIN_SECRET not found in decrypted secrets" >&2
  exit 1
fi

cd "$(dirname "$0")"
hasura metadata apply \
  --endpoint "$ENDPOINT" \
  --admin-secret "$ADMIN_SECRET" \
  "$@"

hasura metadata reload \
  --endpoint "$ENDPOINT" \
  --admin-secret "$ADMIN_SECRET"
