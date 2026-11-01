#!/usr/bin/env bash
# Check a C4-PlantUML source for C4-specific mistakes, then render it.
# Usage: render.sh <source.puml> [--format png|svg]
#
# Rendering itself is delegated to dev10x:diagram-sequence's render.sh,
# so both skills share one PlantUML path (jar lookup, syntax check,
# -pipe output naming, partial-image cleanup).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLANTUML_RENDER="$SCRIPT_DIR/../../diagram-sequence/scripts/render.sh"
C4_MACRO='^[[:space:]]*(Person|System|Container|Component|Deployment_Node|Rel|BiRel)[A-Za-z_]*\('

SOURCE="${1:-}"
if [[ -z "$SOURCE" ]]; then
    echo "Usage: render.sh <source.puml> [--format png|svg]" >&2
    exit 2
fi

case "$SOURCE" in
    *.puml|*.plantuml) ;;
    *)
        echo "ERROR: C4 sources are PlantUML; use a .puml file: $SOURCE" >&2
        exit 2
        ;;
esac

if [[ ! -f "$SOURCE" ]]; then
    echo "ERROR: source file not found: $SOURCE" >&2
    exit 2
fi

if grep -Eq '^[[:space:]]*!include(url)?[[:space:]]+https?://' "$SOURCE"; then
    echo "ERROR: $SOURCE includes C4 over the network. Use the stdlib" \
        "form bundled in the jar, e.g. '!include <C4/C4_Container>' —" \
        "it renders offline and matches the jar's version." >&2
    exit 1
fi

# Network includes were refused above, so any !include left is the stdlib
# form or a local vendored C4 file — both define the macros.
if grep -Eq "$C4_MACRO" "$SOURCE" && ! grep -Eq '^[[:space:]]*!include[[:space:]]+' "$SOURCE"; then
    echo "ERROR: $SOURCE uses C4 macros but has no C4 include. Add one" \
        "line after @startuml: !include <C4/C4_Context>, <C4/C4_Container>," \
        "<C4/C4_Component>, <C4/C4_Dynamic> or <C4/C4_Deployment>." >&2
    exit 1
fi

if ! command -v dot >/dev/null 2>&1; then
    echo "ERROR: Graphviz 'dot' not found — C4 layouts need it." \
        "Install the graphviz package." >&2
    exit 3
fi

exec "$PLANTUML_RENDER" "$@"
