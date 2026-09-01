#!/usr/bin/env bash
# run-playwright.sh — Safe Playwright runner for staging QA
#
# Usage:
#   run-playwright.sh <script.py> [--validate-only]
#                     [--user <username> | --profile <suffix>]
#
# What it does:
#   1. Reads CF Access + CRM credentials from settings.secrets.env
#   2. Validates the Python script syntax (py_compile) before launching a browser
#   3. Exports credentials as env vars (never hardcoded in scripts)
#   4. Runs: VIRTUAL_ENV="" uv run --with "$PLAYWRIGHT_SPEC" python3 <script.py>
#
# Nothing deployment-specific is baked in (GH-1130). Every knob below is
# an environment override with a documented default, and the account map
# is read from the secrets file rather than a case statement — so a third
# credential pair needs no edit to this script, and nobody has to fork it
# and lose the two guarantees it exists to provide.
#
#   STAGING_URL              base URL the scripts hit
#   PLAYWRIGHT_SECRETS_FILE  where the credentials live
#   PLAYWRIGHT_DEFAULT_USER  username when the secrets file names none
#   PLAYWRIGHT_PROFILE       default credential suffix (see below)
#   PLAYWRIGHT_SPEC          the pinned playwright requirement
#
# Accounts are keyed by an optional suffix on the secrets-file keys:
#
#   CRM_USERNAME=…   CRM_PASSWORD=…     -> the default profile
#   CRM_USERNAME2=…  CRM_PASSWORD2=…    -> --profile 2, or --user <its username>
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

# `${VAR:-default}`, like SECRETS_FILE above. An unconditional assignment
# here silently overrode the caller's own environment, so the documented
# `os.environ.get("STAGING_URL", "<real host>")` default in a generated
# script could never apply — every script got the placeholder and failed
# at its first goto with ERR_NAME_NOT_RESOLVED, an error that points at
# DNS rather than at this line (GH-1130).
STAGING_URL="${STAGING_URL:-https://staging-app.example.com}"

# Bounded, like every other dependency pin in this repo (GH-916). An
# unbounded `--with playwright` resolves to whatever is newest on each
# run: one release refused to install a browser at all on a current
# Linux distro, and reported it as "does not support chromium on
# <distro>" — an error that points at the OS rather than the resolver
# (GH-1129).
PLAYWRIGHT_SPEC="${PLAYWRIGHT_SPEC:-playwright>=1.47,<2}"

# ── Parse arguments ────────────────────────────────────────────────────────────
SCRIPT=""
VALIDATE_ONLY=false
USER_ACCOUNT=""
PROFILE="${PLAYWRIGHT_PROFILE:-}"

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
        --profile)
            PROFILE="$2"
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
    echo "Usage: run-playwright.sh <script.py> [--validate-only]" \
         "[--user <username> | --profile <suffix>]" >&2
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

# Read one key out of the secrets file. Empty output means "absent",
# which every caller below checks explicitly.
#
# `|| true` is load-bearing under `set -euo pipefail`: a grep that
# matches nothing exits 1, pipefail propagates that through the pipeline,
# and an unguarded `X=$(...)` assignment then kills the whole script with
# no message at all. An absent optional key is normal here, not fatal.
secret_value() {
    grep -E "^$1=" "$SECRETS_FILE" | head -n1 | cut -d= -f2- || true
}

# Every CRM_USERNAME* key, as "<suffix>=<username>" lines. This is what
# makes the account map config rather than code: a third credential pair
# is two lines in the secrets file, not a new branch here.
username_entries() {
    grep -E "^CRM_USERNAME[A-Za-z0-9_]*=" "$SECRETS_FILE" |
        sed -E 's/^CRM_USERNAME([A-Za-z0-9_]*)=/\1=/' || true
}

known_usernames() {
    local names
    names=$(username_entries | cut -d= -f2- | paste -sd'|' - || true)
    if [[ -z "$names" ]]; then
        echo "(none — this secrets file declares no CRM_USERNAME* keys)"
    else
        echo "$names"
    fi
}

# Source only known keys to avoid polluting the environment
CF_CLIENT_ID=$(secret_value "CF_ACCESS_CLIENT_ID")
CF_SECRET=$(secret_value "CF_ACCESS_CLIENT_SECRET")

if [[ -z "$CF_CLIENT_ID" || -z "$CF_SECRET" ]]; then
    echo "Error: CF_ACCESS_CLIENT_ID or CF_ACCESS_CLIENT_SECRET not found in $SECRETS_FILE" >&2
    exit 1
fi

if [[ -n "$USER_ACCOUNT" && -n "$PROFILE" ]]; then
    echo "Error: pass --user or --profile, not both." >&2
    exit 1
fi

# --user names an account; the suffix carrying it is looked up in the
# secrets file. Naming the suffix directly (--profile) skips the lookup.
if [[ -n "$USER_ACCOUNT" ]]; then
    PROFILE=""
    FOUND=false
    while IFS='=' read -r entry_suffix entry_user; do
        if [[ "$entry_user" == "$USER_ACCOUNT" ]]; then
            PROFILE="$entry_suffix"
            FOUND=true
            break
        fi
    done < <(username_entries)

    if [[ "$FOUND" != "true" ]]; then
        echo "Error: no account '$USER_ACCOUNT' in $SECRETS_FILE." >&2
        echo "  Known: $(known_usernames)" >&2
        echo "  Add a pair to use it, e.g. CRM_USERNAME3=$USER_ACCOUNT and CRM_PASSWORD3=…," >&2
        echo "  then re-run with --user $USER_ACCOUNT (or --profile 3)." >&2
        exit 1
    fi
fi

CRM_USERNAME_RESOLVED=$(secret_value "CRM_USERNAME${PROFILE}")
CRM_PASSWORD_RESOLVED=$(secret_value "CRM_PASSWORD${PROFILE}")

# An unsuffixed run keeps working against a secrets file that only ever
# carried passwords, which is what every deployment had before the map
# became config.
if [[ -z "$CRM_USERNAME_RESOLVED" && -z "$PROFILE" ]]; then
    CRM_USERNAME_RESOLVED="${CRM_USERNAME:-${PLAYWRIGHT_DEFAULT_USER:-e2e_test_user}}"
fi

if [[ -z "$CRM_USERNAME_RESOLVED" ]]; then
    echo "Error: profile '$PROFILE' has no CRM_USERNAME${PROFILE} in $SECRETS_FILE." >&2
    echo "  Add CRM_USERNAME${PROFILE}=<username> alongside its password." >&2
    exit 1
fi

if [[ -z "$CRM_PASSWORD_RESOLVED" ]]; then
    echo "Error: profile '$PROFILE' has no CRM_PASSWORD${PROFILE} in $SECRETS_FILE." >&2
    exit 1
fi

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
echo "Running $SCRIPT as $CRM_USERNAME_RESOLVED ..."

# Every export below is deliberate, and the two kinds are different
# (GH-1130 asked for this audit):
#
#   Credentials and the lib path are set unconditionally BY DESIGN —
#   that is the no-hardcoded-secrets guarantee, and a script inheriting
#   a stale CRM_PASSWORD from a shell would defeat it.
#
#   STAGING_URL is configuration, not a credential, and is resolved with
#   `${VAR:-default}` above so a caller's value survives.
export CF_CLIENT_ID
export CF_SECRET
export CRM_USERNAME="$CRM_USERNAME_RESOLVED"
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

VIRTUAL_ENV="" uv run --with "$PLAYWRIGHT_SPEC" python3 "$SCRIPT"
