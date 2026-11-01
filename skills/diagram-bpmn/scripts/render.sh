#!/usr/bin/env bash
# Validate, lay out, and render a BPMN 2.0 file.
# Usage: render.sh <file.bpmn> [--format png|svg] [--relayout]
#
# A file without diagram interchange (DI) gets coordinates written into
# it — pools, lanes, shapes and edges — so it opens in Camunda Modeler
# or bpmn.io as laid out. Prints "rendered: <path>" on success.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="${DEV10X_BPMN_DEPS:-${XDG_CACHE_HOME:-$HOME/.cache}/dev10x/diagram-bpmn}"

usage() {
    echo "Usage: render.sh <file.bpmn> [--format png|svg] [--relayout]" >&2
    exit 2
}

SOURCE="${1:-}"
[[ -n "$SOURCE" ]] || usage
shift
FORMAT="png"
# A scalar, not an array: "${empty[@]}" trips set -u on bash < 4.4 (macOS).
RELAYOUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --format)
            FORMAT="${2:-}"
            shift 2 || usage
            ;;
        --relayout)
            RELAYOUT="--relayout"
            shift
            ;;
        *) usage ;;
    esac
done

case "$FORMAT" in
    png|svg) ;;
    *)
        echo "ERROR: --format must be png or svg, got '$FORMAT'" >&2
        exit 2
        ;;
esac

case "$SOURCE" in
    *.bpmn) ;;
    *)
        echo "ERROR: expected a .bpmn file: $SOURCE" >&2
        exit 2
        ;;
esac

if [[ ! -f "$SOURCE" ]]; then
    echo "ERROR: source file not found: $SOURCE" >&2
    exit 2
fi

OUTPUT="${SOURCE%.*}.$FORMAT"

for tool in node pnpm; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: '$tool' not found on PATH — the BPMN toolchain needs" \
            "Node.js and pnpm." >&2
        exit 3
    fi
done

# shellcheck source=../../diagram-sequence/scripts/_chrome.sh
. "$SCRIPT_DIR/../../diagram-sequence/scripts/_chrome.sh"

ensure_toolchain() {
    if cmp -s "$SCRIPT_DIR/package.json" "$DEPS_DIR/package.json" \
        && cmp -s "$SCRIPT_DIR/pnpm-workspace.yaml" "$DEPS_DIR/pnpm-workspace.yaml" \
        && [[ -x "$DEPS_DIR/node_modules/.bin/bpmn-to-image" ]]; then
        return 0
    fi
    mkdir -p "$DEPS_DIR"
    cp "$SCRIPT_DIR/package.json" "$SCRIPT_DIR/pnpm-workspace.yaml" "$DEPS_DIR/"
    # The cache's pnpm-lock.yaml is private to it and records the previous
    # pins; a frozen install would refuse every pin change as outdated.
    if ! pnpm --dir "$DEPS_DIR" install --silent --no-frozen-lockfile; then
        # Drop the copied pins so the next run reinstalls instead of
        # trusting a node_modules left over from the previous pins.
        rm -f "$DEPS_DIR/package.json"
        echo "ERROR: could not install the BPMN toolchain into $DEPS_DIR" >&2
        exit 3
    fi
}

ensure_toolchain

node "$SCRIPT_DIR/layout.mjs" "$DEPS_DIR" "$SOURCE" ${RELAYOUT:+"$RELAYOUT"}

if [[ -z "${PUPPETEER_EXECUTABLE_PATH:-}" ]]; then
    if chrome="$(find_chrome)"; then
        export PUPPETEER_EXECUTABLE_PATH="$chrome"
    else
        echo "ERROR: no Chrome/Chromium on PATH for rendering. Install one or" \
            "set PUPPETEER_EXECUTABLE_PATH. The laid-out $SOURCE is still valid" \
            "and opens in Camunda Modeler." >&2
        exit 3
    fi
fi

rm -f "$OUTPUT"
"$DEPS_DIR/node_modules/.bin/bpmn-to-image" --no-footer "$SOURCE:$OUTPUT" >/dev/null

if [[ ! -s "$OUTPUT" ]]; then
    echo "ERROR: renderer exited cleanly but wrote no image at $OUTPUT" >&2
    exit 4
fi

echo "rendered: $OUTPUT"
