#!/usr/bin/env bash
# Smoke-test a dev release locally before shipping.
#
# Validates the surfaces that neither CI (runs under mocks) nor
# `claude --plugin-dir` (runs source, not the package) exercise:
#
#   1. The built wheel installs cleanly into an isolated venv.
#   2. The packaged `dev10x` CLI entry point resolves and runs.
#   3. The packaged MCP server modules import (proves src/ + *.yaml
#      package-data actually ship in the wheel).
#   4. The plugin structure verifies (.claude-plugin/scripts/verify.sh).
#
# It then prints the `claude --plugin-dir` command that exercises the
# live plugin runtime (MCP from src + hooks).
#
# This script is side-effect-light: it builds and installs into a
# throwaway temp dir and NEVER writes to ~/.claude, never tags, never
# pushes. Safe to run unattended.
#
# Usage: ./bin/test-local.sh [--keep] [--no-verify]
#   --keep        Keep the temp build dir + venv for inspection.
#   --no-verify   Skip the .claude-plugin/scripts/verify.sh structure check.
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

KEEP=0
RUN_VERIFY=1

for arg in "$@"; do
    case "$arg" in
        --keep) KEEP=1 ;;
        --no-verify) RUN_VERIFY=0 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--keep] [--no-verify]" >&2
            exit 1
            ;;
    esac
done

command -v uv >/dev/null || {
    echo "uv not found. Install: https://docs.astral.sh/uv/" >&2
    exit 1
}

REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/dev10x-test-local.XXXXXX")"

# setuptools writes build/ and src/*.egg-info/ into the project tree during
# the build. Track whether they pre-existed so cleanup removes only what this
# run created and never deletes a developer's own build artifacts.
BUILD_DIR="$REPO_ROOT/build"
EGG_INFO="$REPO_ROOT/src/Dev10x.egg-info"
[[ -e "$BUILD_DIR" ]] && PREEXISTING_BUILD=1 || PREEXISTING_BUILD=0
[[ -e "$EGG_INFO" ]] && PREEXISTING_EGG=1 || PREEXISTING_EGG=0

function cleanup {
    if [[ "$KEEP" == "1" ]]; then
        echo -e "  ${YELLOW}--keep set; left build dir at: ${WORKDIR}${RESET}"
        return
    fi
    rm -rf "$WORKDIR"
    [[ "$PREEXISTING_BUILD" == "0" ]] && rm -rf "$BUILD_DIR"
    [[ "$PREEXISTING_EGG" == "0" ]] && rm -rf "$EGG_INFO"
}
trap cleanup EXIT

function header {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${CYAN}  $1${RESET}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
}

function step {
    echo -e "  ${GREEN}▸${RESET} $1"
}

header "Phase 1 · Build the wheel"
step "Building into ${WORKDIR}/dist ..."
uv build --project "$REPO_ROOT" --wheel --out-dir "$WORKDIR/dist"

wheel="$(find "$WORKDIR/dist" -name '*.whl' | head -n1)"
if [[ -z "$wheel" ]]; then
    echo -e "  ${RED}✗ No wheel produced by uv build${RESET}" >&2
    exit 1
fi
step "Wheel: $(basename "$wheel")"

header "Phase 2 · Install into an isolated venv"
venv="$WORKDIR/venv"
step "Creating venv ..."
uv venv "$venv" >/dev/null
# Install the freshly-built wheel plus `mcp` — the plugin runtime supplies
# `mcp` via each server's PEP 723 metadata, but it is not a wheel dependency.
step "Installing wheel + mcp ..."
uv pip install --python "$venv/bin/python" "$wheel" "mcp>=1.0" >/dev/null

header "Phase 3 · Smoke the packaged artifact"
step "dev10x --help ..."
"$venv/bin/dev10x" --help >/dev/null
step "import dev10x.mcp.server_cli, dev10x.mcp.server_db ..."
"$venv/bin/python" -c "import dev10x.mcp.server_cli, dev10x.mcp.server_db"
echo -e "  ${GREEN}✓ Packaged CLI + MCP server modules import cleanly${RESET}"

if [[ "$RUN_VERIFY" == "1" ]]; then
    header "Phase 4 · Verify plugin structure"
    bash "$REPO_ROOT/.claude-plugin/scripts/verify.sh"
fi

header "Next · Exercise the live plugin runtime"
echo ""
echo -e "  The wheel + structure are sound. To exercise the actual plugin"
echo -e "  runtime (MCP servers from ${BOLD}src/${RESET} + hooks), launch a real session:"
echo ""
echo -e "    ${CYAN}claude --plugin-dir ${REPO_ROOT}${RESET}"
echo ""
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}✅ Local smoke passed${RESET}"
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
