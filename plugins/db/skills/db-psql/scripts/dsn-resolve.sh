#!/usr/bin/env bash
# Resolve a database DSN from env var or system keyring.
#
# Usage:
#   dsn-resolve.sh --backend env --env-var DB_NAME
#   dsn-resolve.sh --backend keyring --service S --account A

set -euo pipefail

BACKEND=""
ENV_VAR=""
KEYRING_SERVICE=""
KEYRING_ACCOUNT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)   BACKEND="$2"; shift 2 ;;
    --env-var)   ENV_VAR="$2"; shift 2 ;;
    --service)   KEYRING_SERVICE="$2"; shift 2 ;;
    --account)   KEYRING_ACCOUNT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

case "$BACKEND" in
  env)
    if [[ -z "$ENV_VAR" ]]; then
      echo "ERROR: --env-var required for backend=env" >&2
      exit 1
    fi
    DSN="${!ENV_VAR:-}"
    if [[ -z "$DSN" ]]; then
      echo "ERROR: Environment variable $ENV_VAR is not set." >&2
      echo "Set it to the read-only DSN in your shell profile." >&2
      exit 1
    fi
    echo "$DSN"
    ;;
  keyring)
    if [[ -z "$KEYRING_SERVICE" || -z "$KEYRING_ACCOUNT" ]]; then
      echo "ERROR: --service and --account required for backend=keyring" >&2
      exit 1
    fi
    OS="$(uname -s)"
    if [[ "$OS" == "Darwin" ]]; then
      DSN=$(security find-generic-password -s "$KEYRING_SERVICE" -a "$KEYRING_ACCOUNT" -w) || {
        echo "ERROR: No Keychain entry for service=$KEYRING_SERVICE account=$KEYRING_ACCOUNT" >&2
        echo "Store it with:" >&2
        echo "  security add-generic-password -s $KEYRING_SERVICE -a $KEYRING_ACCOUNT -w" >&2
        exit 1
      }
    else
      if ! command -v secret-tool &>/dev/null; then
        echo "ERROR: secret-tool not found. Install libsecret-tools." >&2
        exit 1
      fi
      DSN=$(secret-tool lookup service "$KEYRING_SERVICE" account "$KEYRING_ACCOUNT") || {
        echo "ERROR: No keyring entry for service=$KEYRING_SERVICE account=$KEYRING_ACCOUNT" >&2
        echo "Store it with:" >&2
        echo "  secret-tool store --label \"$KEYRING_SERVICE $KEYRING_ACCOUNT\" \\" >&2
        echo "    service $KEYRING_SERVICE account $KEYRING_ACCOUNT" >&2
        exit 1
      }
    fi
    echo "$DSN"
    ;;
  *)
    echo "ERROR: Unknown backend: $BACKEND (expected: env, keyring)" >&2
    exit 1
    ;;
esac
