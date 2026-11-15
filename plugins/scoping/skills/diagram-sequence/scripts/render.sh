#!/usr/bin/env bash
# Validate and render a sequence diagram source file.
# Usage: render.sh <source.mmd|source.puml> [--format png|svg]
#
# Prints "rendered: <path>" on success. Any syntax error exits non-zero
# with the renderer's own message on stderr, so a broken diagram can
# never be reported as done.

set -euo pipefail

MERMAID_CLI="@mermaid-js/mermaid-cli@11.17.1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLED_JAR="$SCRIPT_DIR/../../scope/bin/plantuml.jar"
# GH-1783: SANDBOX refuses local !include and blanks %getenv(); the
# bundled <C4/...> stdlib still resolves. Override only for a trusted source.
SECURITY_PROFILE="${PLANTUML_SECURITY_PROFILE:-SANDBOX}"

usage() {
    echo "Usage: render.sh <source.mmd|source.puml> [--format png|svg]" >&2
    exit 2
}

SOURCE="${1:-}"
[[ -n "$SOURCE" ]] || usage
shift
FORMAT="png"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --format)
            FORMAT="${2:-}"
            shift 2 || usage
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

if [[ ! -f "$SOURCE" ]]; then
    echo "ERROR: source file not found: $SOURCE" >&2
    exit 2
fi

OUTPUT="${SOURCE%.*}.$FORMAT"

find_plantuml_jar() {
    local candidate
    for candidate in "${PLANTUML_JAR:-}" "$BUNDLED_JAR" "$HOME/.local/bin/plantuml.jar"; do
        if [[ -n "$candidate" && -f "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# shellcheck source=_chrome.sh
. "$SCRIPT_DIR/_chrome.sh"

run_plantuml() {
    local jar="$1"
    shift
    java -Djava.awt.headless=true "-DPLANTUML_SECURITY_PROFILE=$SECURITY_PROFILE" \
        -jar "$jar" "$@"
}

render_plantuml() {
    # PlantUML falls back to its permissive default on an unknown name.
    case "$SECURITY_PROFILE" in
        SANDBOX|ALLOWLIST|INTERNET|UNSECURE|LEGACY) ;;
        *)
            echo "ERROR: PLANTUML_SECURITY_PROFILE must be SANDBOX, ALLOWLIST," \
                "INTERNET, UNSECURE or LEGACY, got '$SECURITY_PROFILE'" >&2
            exit 2
            ;;
    esac
    # Every failure below must leave no image: a stale one next to a
    # broken source reads as the current diagram.
    rm -f "$OUTPUT"
    local jar
    if ! jar="$(find_plantuml_jar)"; then
        echo "ERROR: no PlantUML jar found. Set PLANTUML_JAR or install" \
            "$HOME/.local/bin/plantuml.jar." >&2
        exit 3
    fi
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: 'java' not found on PATH — PlantUML needs a Java runtime (11+)." >&2
        exit 3
    fi
    local report status=0
    report="$(run_plantuml "$jar" -syntax <"$SOURCE")" || status=$?
    if [[ "$(head -n 1 <<<"$report")" == "ERROR" ]]; then
        local line message
        line="$(($(sed -n 2p <<<"$report") + 1))"
        message="$(sed -n '3,$p' <<<"$report")"
        echo "ERROR: syntax error at line $line of $SOURCE: $message" >&2
        exit 1
    fi
    if [[ $status -ne 0 ]]; then
        echo "ERROR: the PlantUML syntax check could not run (java exit $status)" >&2
        exit 3
    fi
    # -pipe writes to the path we choose; file mode names the output
    # after `@startuml <name>`, which need not match the source file.
    if ! run_plantuml "$jar" -failfast2 -pipe "-t$FORMAT" <"$SOURCE" >"$OUTPUT"; then
        rm -f "$OUTPUT"
        echo "ERROR: PlantUML failed to render $SOURCE" >&2
        exit 1
    fi
}

render_mermaid() {
    rm -f "$OUTPUT"
    if [[ -z "${PUPPETEER_EXECUTABLE_PATH:-}" ]]; then
        local chrome
        if chrome="$(find_chrome)"; then
            export PUPPETEER_EXECUTABLE_PATH="$chrome"
        fi
    fi
    local status=0
    pnpm --silent dlx "$MERMAID_CLI" --quiet --input "$SOURCE" --output "$OUTPUT" \
        2> >(grep -v '^    at ' >&2) || status=$?
    if [[ $status -ne 0 ]]; then
        echo "ERROR: mermaid-cli failed on $SOURCE (exit $status)" >&2
        exit 1
    fi
}

case "$SOURCE" in
    *.puml|*.plantuml) render_plantuml ;;
    *.mmd|*.mermaid) render_mermaid ;;
    *)
        echo "ERROR: unsupported extension (use .mmd or .puml): $SOURCE" >&2
        exit 2
        ;;
esac

if [[ ! -s "$OUTPUT" ]]; then
    echo "ERROR: renderer exited cleanly but wrote no image at $OUTPUT" >&2
    exit 4
fi

echo "rendered: $OUTPUT"
