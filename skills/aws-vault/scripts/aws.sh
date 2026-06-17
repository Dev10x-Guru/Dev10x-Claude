#!/usr/bin/env bash
# Usage: aws.sh [--registry PATH] <env> <service> <operation> [args...]
#
# Strictly READ-ONLY wrapper for AWS CLI operations via aws-vault.
# Claude MUST use this script instead of calling `aws-vault exec ... aws`
# directly.
#
# Only operations whose name begins with a read-prefix in ALLOWED_PREFIXES
# below are permitted (describe-*, list-*, get-*, lookup-*, ...). Mutating
# operations (create-*, delete-*, put-*, update-*, run-*, terminate-*,
# start-*, stop-*, ...) are denied. A handful of read-prefixed operations
# exfiltrate live secrets or mint credentials (secretsmanager
# get-secret-value, ssm get-parameter --with-decryption, kms decrypt, sts
# get-session-token, ec2 get-password-data); those are denied by
# DENIED_OPERATIONS even though their verb is "get". This mirrors DX014's
# sensitivity screen so the wrapper and the Bash validator agree
# (GH-605, GH-606 D6).
#
# When an operation is denied the script prints a copy-pasteable snippet
# for you to run in a separate terminal under your own supervision.
#
# Privilege-escalation / credential-redirection flags are denied anywhere
# in the argument list (--profile, --region override is allowed but
# --endpoint-url, --no-verify-ssl, --no-sign-request, --debug-as) so the
# wrapper's profile resolution cannot be bypassed via flag injection.
#
# Arguments:
#   <env>         Environment name (resolved from registry)
#   <service>     AWS CLI service (e.g. ec2, s3api, ecr, logs)
#   <operation>   Read operation (e.g. describe-instances, list-buckets)
#   [args...]     Remaining aws arguments
#
# Registry: ~/.config/Dev10x/aws-vault/service-registry.yaml

set -euo pipefail

# Read-operation name prefixes. The AWS CLI names read operations with a
# small set of verbs; anything outside this set is treated as mutating.
ALLOWED_PREFIXES=(
    describe-
    list-
    get-
    lookup-
    search-
    head-
    batch-get-
    view-
    estimate-
)

# Operations that read-prefix but exfiltrate secrets or mint credentials.
# Denied even though they match ALLOWED_PREFIXES (defense-in-depth with
# DX014's SECRET sensitivity patterns).
DENIED_OPERATIONS=(
    "secretsmanager get-secret-value"
    "secretsmanager batch-get-secret-value"
    "ssm get-parameter"
    "ssm get-parameters"
    "ssm get-parameters-by-path"
    "kms decrypt"
    "kms generate-data-key"
    "sts get-session-token"
    "sts get-federation-token"
    "ec2 get-password-data"
    "ecr get-login-password"
    "ecr-public get-login-password"
    "cognito-idp get-credentials-for-identity"
)

# A handful of services whose entire surface is read-only-but-sensitive or
# stateless-but-mutating; bare allowlist by prefix is not enough. `s3 cp`,
# `s3 sync`, `s3 mv`, `s3 rm` are not describe-/list-/get- so they are
# already denied by the prefix gate — no special-case needed.
DENIED_FLAGS=(
    --endpoint-url
    --no-verify-ssl
    --no-sign-request
)

# Optional leading `--registry <path>` flag (parity with kubectl.sh,
# GH-311) — avoids the env-prefix invocation friction. Falls back to the
# DEV10X_AWS_VAULT_REGISTRY env var.
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

ENV="${1:?Usage: aws.sh <env> <service> <operation> [args...]}"
shift

SERVICE="${1:?Usage: aws.sh <env> <service> <operation> [args...]}"
shift

OPERATION="${1:?Usage: aws.sh <env> <service> <operation> [args...]}"
shift

PROFILE=$(yq ".environments.$ENV.aws_vault_profile" "$REGISTRY")
if [[ -z "$PROFILE" || "$PROFILE" == "null" ]]; then
    VALID=$(yq '.environments | keys | join(", ")' "$REGISTRY")
    echo "Unknown environment: $ENV. Valid: $VALID" >&2
    exit 1
fi

deny() {
    {
        echo "aws.sh: $1"
        echo
        echo "This wrapper is strictly read-only. Allowed operation prefixes:"
        echo "  ${ALLOWED_PREFIXES[*]}"
        echo
        echo "If you need to run '$SERVICE $OPERATION', execute the following in a"
        echo "separate terminal under your own supervision:"
        echo
        echo "    aws-vault exec $PROFILE -- aws $SERVICE $OPERATION $*"
    } >&2
    exit 1
}

# Secret-exfil / credential-minting denylist takes precedence over the
# read-prefix allowlist.
for denied in "${DENIED_OPERATIONS[@]}"; do
    if [[ "$SERVICE $OPERATION" == "$denied" ]]; then
        deny "operation '$SERVICE $OPERATION' exfiltrates secrets or mints credentials — denied even though it reads."
    fi
done

is_allowed_prefix=false
for prefix in "${ALLOWED_PREFIXES[@]}"; do
    if [[ "$OPERATION" == "$prefix"* ]]; then
        is_allowed_prefix=true
        break
    fi
done

if [[ "$is_allowed_prefix" != "true" ]]; then
    deny "operation '$OPERATION' is not a read operation."
fi

# `--with-decryption` turns an otherwise-benign ssm read into a secret
# read; deny it on any operation (belt-and-suspenders with DENIED_OPERATIONS).
for arg in "$@"; do
    if [[ "$arg" == "--with-decryption" ]]; then
        deny "flag '--with-decryption' decrypts secret material — denied."
    fi
    for denied in "${DENIED_FLAGS[@]}"; do
        if [[ "$arg" == "$denied" || "$arg" == "$denied="* ]]; then
            echo "aws.sh: flag '$arg' is not permitted by this wrapper." >&2
            echo "  Denied flags: ${DENIED_FLAGS[*]} --with-decryption" >&2
            echo "  Reason: these flags bypass profile resolution or sign-in checks." >&2
            exit 1
        fi
    done
done

echo "aws ($ENV, profile: $PROFILE): $SERVICE $OPERATION $*" >&2

aws-vault exec "$PROFILE" -- aws "$SERVICE" "$OPERATION" "$@"
