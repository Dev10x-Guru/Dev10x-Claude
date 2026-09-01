#!/usr/bin/env bash
# run-playwright.sh — Safe Playwright runner for ExampleCorp staging QA
#
# Usage:
#   run-playwright.sh <script.py> [--validate-only] [--user janusz_ai]
#
# What it does:
#   1. Reads CF Access + CRM credentials from settings.secrets.env
#   2. Validates the Python script syntax (py_compile) before launching a browser
#   3. Exports credentials as env vars (never hardcoded in scripts)
#   4. Runs: VIRTUAL_ENV="" uv run --with playwright python3 <script.py>
#
# Scripts must read credentials via os.environ:
#   CF_CLIENT_ID, CF_SECRET, CRM_USERNAME, CRM_PASSWORD, STAGING_URL
#
# Scripts import the shared annotation module via os.environ:
#   DEV10X_PLAYWRIGHT_LIB  (skills/playwright/lib)
#   DEV10X_TTS_SCRIPT      (skills/tts/scripts/synthesize.py, for narration)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(cd "${SCRIPTS_DIR}/../lib" && pwd)"
SKILLS_DIR="$(cd "${SCRIPTS_DIR}/../.." && pwd)"

SECRETS_FILE="${PLAYWRIGHT_SECRETS_FILE:-/work/example/app-e2e/settings.secrets.env}"
STAGING_URL="https://staging-app.example.com"

# ── Parse arguments ────────────────────────────────────────────────────────────
SCRIPT=""
VALIDATE_ONLY=false
USER_ACCOUNT="e2e_test_user"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --validate-only)
            VALIDATE_ONLY=true
            shift
            ;;
        --user)
            USER_ACCOUNT="$2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            SCRIPT="$1"
            shift
            ;;
    esac
done

if [[ -z "$SCRIPT" ]]; then
    echo "Usage: run-playwright.sh <script.py> [--validate-only] [--user janusz_ai]" >&2
    exit 1
fi

if [[ ! -f "$SCRIPT" ]]; then
    echo "Error: script not found: $SCRIPT" >&2
    exit 1
fi

# ── Load credentials ───────────────────────────────────────────────────────────
if [[ ! -f "$SECRETS_FILE" ]]; then
    echo "Error: secrets file not found: $SECRETS_FILE" >&2
    exit 1
fi

# Source only known keys to avoid polluting the environment
CF_CLIENT_ID=$(grep -E "^CF_ACCESS_CLIENT_ID=" "$SECRETS_FILE" | cut -d= -f2-)
CF_SECRET=$(grep -E "^CF_ACCESS_CLIENT_SECRET=" "$SECRETS_FILE" | cut -d= -f2-)
CRM_PASSWORD=$(grep -E "^CRM_PASSWORD=" "$SECRETS_FILE" | cut -d= -f2-)
CRM_PASSWORD2=$(grep -E "^CRM_PASSWORD2=" "$SECRETS_FILE" | cut -d= -f2-)

if [[ -z "$CF_CLIENT_ID" || -z "$CF_SECRET" ]]; then
    echo "Error: CF_ACCESS_CLIENT_ID or CF_ACCESS_CLIENT_SECRET not found in $SECRETS_FILE" >&2
    exit 1
fi

# Select CRM credentials based on --user
case "$USER_ACCOUNT" in
    e2e_test_user)
        CRM_USERNAME="e2e_test_user"
        CRM_PASSWORD_RESOLVED="$CRM_PASSWORD"
        ;;
    janusz_ai)
        CRM_USERNAME="janusz_ai"
        CRM_PASSWORD_RESOLVED="$CRM_PASSWORD2"
        ;;
    *)
        echo "Error: unknown --user value '$USER_ACCOUNT'. Use: e2e_test_user | janusz_ai" >&2
        exit 1
        ;;
esac

# ── Syntax validation ──────────────────────────────────────────────────────────
echo "Validating $SCRIPT ..."
if ! python3 -m py_compile "$SCRIPT" 2>&1; then
    echo "Syntax error in $SCRIPT — aborting." >&2
    exit 1
fi
echo "  Syntax OK"

if [[ "$VALIDATE_ONLY" == "true" ]]; then
    echo "  --validate-only: skipping execution"
    exit 0
fi

# ── Execute ────────────────────────────────────────────────────────────────────
echo "Running $SCRIPT as $CRM_USERNAME ..."
export CF_CLIENT_ID
export CF_SECRET
export CRM_USERNAME="$CRM_USERNAME"
export CRM_PASSWORD="$CRM_PASSWORD_RESOLVED"
export STAGING_URL
export DEV10X_PLAYWRIGHT_LIB="$LIB_DIR"
# narration.py shells out to this wrapper rather than to piper, so the
# generated script never hard-codes a path to either.
#
# A missing wrapper is warned about but NOT fatal: narration is opt-in and
# most captures are silent, so exiting here would break runs that never
# wanted audio. Leaving the variable unset makes narration.py raise its own
# actionable error, which only a narrated run will ever reach.
DEV10X_TTS_SCRIPT="${SKILLS_DIR}/tts/scripts/synthesize.py"
if [[ -f "$DEV10X_TTS_SCRIPT" ]]; then
    export DEV10X_TTS_SCRIPT
else
    echo "Warning: TTS wrapper not found at $DEV10X_TTS_SCRIPT" >&2
    echo "  Narration will be unavailable; silent capture is unaffected." >&2
    unset DEV10X_TTS_SCRIPT
fi

VIRTUAL_ENV="" uv run --with playwright python3 "$SCRIPT"
