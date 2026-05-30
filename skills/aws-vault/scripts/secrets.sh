#!/usr/bin/env bash
# Usage: secrets.sh [--registry PATH] <env> <service|secret-id> [--key KEY_NAME]
#
# Approved wrapper for AWS Secrets Manager access via aws-vault.
# Claude MUST use this script instead of calling aws secretsmanager directly.
# Claude MUST ask the user for confirmation before invoking this script.
#
# Arguments:
#   <env>               Environment name (resolved from registry)
#   <service|secret-id> Known service name or raw secret ID
#   --key KEY_NAME      Extract a specific key from the JSON blob (optional)
#
# Registry: ~/.config/Dev10x/aws-vault/service-registry.yaml
# (copy the plugin's references/service-registry.example.yaml to seed it)

set -euo pipefail

# Optional leading `--registry <path>` flag (GH-311) — avoids the env-prefix
# invocation friction. Falls back to the DEV10X_AWS_VAULT_REGISTRY env var.
if [[ "${1:-}" == "--registry" ]]; then
    DEV10X_AWS_VAULT_REGISTRY="${2:?--registry requires a path}"
    shift 2
fi

REGISTRY="${DEV10X_AWS_VAULT_REGISTRY:-$HOME/.config/Dev10x/aws-vault/service-registry.yaml}"

if [[ ! -f "$REGISTRY" ]]; then
    echo "Registry not found: $REGISTRY" >&2
    echo "Copy the example from the plugin:" >&2
    echo "  mkdir -p ~/.config/Dev10x/aws-vault" >&2
    echo "  cp \${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/references/service-registry.example.yaml \\" >&2
    echo "     ~/.config/Dev10x/aws-vault/service-registry.yaml" >&2
    exit 1
fi

ENV="${1:?Usage: secrets.sh <env> <service|secret-id> [--key KEY_NAME]}"
SERVICE_OR_ID="${2:?Usage: secrets.sh <env> <service|secret-id> [--key KEY_NAME]}"
KEY=""

shift 2
while [[ $# -gt 0 ]]; do
    case "$1" in
        --key) KEY="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

PROFILE=$(yq ".environments.$ENV.aws_vault_profile" "$REGISTRY")
if [[ -z "$PROFILE" || "$PROFILE" == "null" ]]; then
    VALID=$(yq '.environments | keys | join(", ")' "$REGISTRY")
    echo "Unknown environment: $ENV. Valid: $VALID" >&2
    exit 1
fi

SECRET_ID=$(yq ".environments.$ENV.secrets.\"$SERVICE_OR_ID\" // \"$SERVICE_OR_ID\"" "$REGISTRY")

echo "Fetching secret: $SECRET_ID  env=$ENV  profile=$PROFILE${KEY:+  key=$KEY}" >&2

if [[ -n "$KEY" ]]; then
    aws-vault exec "$PROFILE" -- aws secretsmanager get-secret-value \
        --secret-id "$SECRET_ID" \
        --query SecretString \
        --output text | jq -r --arg k "$KEY" '.[$k]'
else
    aws-vault exec "$PROFILE" -- aws secretsmanager get-secret-value \
        --secret-id "$SECRET_ID" \
        --query SecretString \
        --output text
fi
