#!/usr/bin/env bash
# Usage: kubectl.sh <env> <kubectl-verb> [args...]
#
# Strictly READ-ONLY wrapper for kubectl operations via aws-vault.
# Claude MUST use this script instead of calling kubectl directly.
#
# Only the verbs listed in ALLOWED_VERBS below are permitted. Mutating
# operations (apply, create, delete, patch, scale, exec, port-forward,
# etc.) are denied. If you need to run a mutating command, the script
# prints a copy-pasteable snippet for you to execute in a separate
# terminal under your own supervision.
#
# Privilege-escalation and cluster-redirection flags are also denied
# anywhere in the argument list (--as, --as-group, --token, --server,
# --kubeconfig, --insecure-skip-tls-verify) so the verb allowlist
# cannot be bypassed via flag injection.
#
# Arguments:
#   <env>           Environment name (resolved from registry)
#   <kubectl-verb>  One of: get, describe, logs, top, events, explain,
#                   version, cluster-info, api-resources, api-versions,
#                   auth, wait, diff
#   [args...]       Remaining kubectl arguments (selectors, names, flags)
#
# Registry: ~/.config/Dev10x/aws-vault/service-registry.yaml

set -euo pipefail

ALLOWED_VERBS=(
    get
    describe
    logs
    top
    events
    explain
    version
    cluster-info
    api-resources
    api-versions
    auth
    wait
    diff
)

DENIED_FLAG_PREFIXES=(
    --as
    --as-group
    --token
    --server
    --kubeconfig
    --insecure-skip-tls-verify
)

REGISTRY="${DEV10X_AWS_VAULT_REGISTRY:-$HOME/.config/Dev10x/aws-vault/service-registry.yaml}"

if [[ ! -f "$REGISTRY" ]]; then
    echo "Registry not found: $REGISTRY" >&2
    echo "Copy the example from the plugin:" >&2
    echo "  mkdir -p ~/.config/Dev10x/aws-vault" >&2
    echo "  cp \${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/references/service-registry.example.yaml \\" >&2
    echo "     ~/.config/Dev10x/aws-vault/service-registry.yaml" >&2
    exit 1
fi

ENV="${1:?Usage: kubectl.sh <env> <kubectl-verb> [args...]}"
shift

VERB="${1:?Usage: kubectl.sh <env> <kubectl-verb> [args...]}"
shift

is_allowed_verb=false
for allowed in "${ALLOWED_VERBS[@]}"; do
    if [[ "$VERB" == "$allowed" ]]; then
        is_allowed_verb=true
        break
    fi
done

PROFILE=$(yq ".environments.$ENV.aws_vault_profile" "$REGISTRY")
if [[ -z "$PROFILE" || "$PROFILE" == "null" ]]; then
    VALID=$(yq '.environments | keys | join(", ")' "$REGISTRY")
    echo "Unknown environment: $ENV. Valid: $VALID" >&2
    exit 1
fi

CONTEXT=$(yq ".environments.$ENV.k8s.context" "$REGISTRY")
if [[ -z "$CONTEXT" || "$CONTEXT" == "null" ]]; then
    echo "Missing k8s.context for environment: $ENV" >&2
    exit 1
fi
NAMESPACE=$(yq ".environments.$ENV.k8s.namespace // \"default\"" "$REGISTRY")

if [[ "$is_allowed_verb" != "true" ]]; then
    {
        echo "kubectl.sh: verb '$VERB' is not permitted by this wrapper."
        echo
        echo "This wrapper is strictly read-only. Allowed verbs:"
        echo "  ${ALLOWED_VERBS[*]}"
        echo
        echo "If you need to run '$VERB', execute the following in a"
        echo "separate terminal under your own supervision:"
        echo
        echo "    aws-vault exec $PROFILE -- \\"
        echo "      kubectl --context $CONTEXT --namespace $NAMESPACE \\"
        echo "      $VERB $*"
    } >&2
    exit 1
fi

for arg in "$@"; do
    for denied in "${DENIED_FLAG_PREFIXES[@]}"; do
        if [[ "$arg" == "$denied" || "$arg" == "$denied="* ]]; then
            echo "kubectl.sh: flag '$arg' is not permitted by this wrapper." >&2
            echo "  Denied flag prefixes: ${DENIED_FLAG_PREFIXES[*]}" >&2
            echo "  Reason: these flags bypass the wrapper's profile/context/namespace resolution" >&2
            echo "  or escalate privileges (impersonation, alternate credentials, alternate cluster)." >&2
            exit 1
        fi
    done
done

echo "kubectl ($ENV, context: $CONTEXT, namespace: $NAMESPACE): $VERB $*" >&2

aws-vault exec "$PROFILE" -- kubectl --context "$CONTEXT" --namespace "$NAMESPACE" "$VERB" "$@"
