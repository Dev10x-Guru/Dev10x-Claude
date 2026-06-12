#!/usr/bin/env bash
# Generate a new skill directory with complete boilerplate.
# Usage: scaffold.sh <skill-name> <pattern>
#   skill-name: e.g. "my-feature" (will become Dev10x:my-feature)
#   pattern:    script|orchestration|reference

set -euo pipefail

SKILL_NAME="${1:-}"
PATTERN="${2:-orchestration}"

if [[ -z "$SKILL_NAME" ]]; then
    echo "Usage: scaffold.sh <skill-name> [script|orchestration|reference]"
    echo "  skill-name: feature name (e.g., my-feature)"
    echo "  pattern: skill pattern (default: orchestration)"
    exit 1
fi

if [[ "$PATTERN" != "script" && "$PATTERN" != "orchestration" && "$PATTERN" != "reference" ]]; then
    echo "ERROR: Unknown pattern '$PATTERN'. Use: script, orchestration, or reference"
    exit 1
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SKILL_DIR="$PLUGIN_ROOT/skills/$SKILL_NAME"

if [[ -d "$SKILL_DIR" ]]; then
    echo "ERROR: Skill directory already exists: $SKILL_DIR"
    exit 1
fi

mkdir -p "$SKILL_DIR"

INVOCATION_NAME="Dev10x:$SKILL_NAME"

generate_skill_md() {
    local allowed_tools=""
    case "$PATTERN" in
        script)
            allowed_tools="  - Bash(\${CLAUDE_PLUGIN_ROOT}/skills/$SKILL_NAME/scripts/:*)
  - AskUserQuestion"
            ;;
        orchestration)
            allowed_tools="  - AskUserQuestion"
            ;;
        reference)
            allowed_tools="  - AskUserQuestion"
            ;;
    esac

    cat <<SKILL_EOF
---
name: $INVOCATION_NAME
description: >
  Use when [situation trigger] — so [what the user gains].
user-invocable: true
invocation-name: $INVOCATION_NAME
allowed-tools:
$allowed_tools
---

# $INVOCATION_NAME

**Announce:** "Using $INVOCATION_NAME to [purpose]."

## Orchestration

This skill follows \`references/task-orchestration.md\` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. \`TaskCreate(subject="Run $INVOCATION_NAME", activeForm="Running")\`

Mark completed when done: \`TaskUpdate(taskId, status="completed")\`

## Overview

TODO: Describe what this skill does and when to use it.

## Workflow

### Step 1: Gather Context

TODO: Define information gathering step.

### Step 2: Execute

TODO: Define main execution step.

### Step 3: Verify

TODO: Define verification step.
SKILL_EOF
}

generate_skill_md > "$SKILL_DIR/SKILL.md"

mkdir -p "$SKILL_DIR/evals"
cat <<EVALS_EOF > "$SKILL_DIR/evals/evals.json"
{
  "skill_name": "$INVOCATION_NAME",
  "eval_dimensions": [
    {
      "name": "task_tracking",
      "description": "Creates and updates tasks per orchestration contract"
    },
    {
      "name": "announce",
      "description": "Opens with announce line identifying the skill"
    }
  ],
  "evals": []
}
EVALS_EOF

if [[ "$PATTERN" == "script" ]]; then
    mkdir -p "$SKILL_DIR/scripts"
    cat <<SCRIPT_EOF > "$SKILL_DIR/scripts/run.sh"
#!/usr/bin/env bash
# TODO: Implement skill script
set -euo pipefail

echo "TODO: Implement $INVOCATION_NAME"
SCRIPT_EOF
    chmod +x "$SKILL_DIR/scripts/run.sh"
fi

if [[ "$PATTERN" == "reference" ]]; then
    mkdir -p "$SKILL_DIR/references"
    cat <<REF_EOF > "$SKILL_DIR/references/guide.md"
# $INVOCATION_NAME Reference

TODO: Add reference documentation.
REF_EOF
fi

echo "Created skill: $SKILL_DIR"
echo "  Pattern: $PATTERN"
echo "  Invocation: $INVOCATION_NAME"
echo ""
echo "Files created:"
find "$SKILL_DIR" -type f | sort | while IFS= read -r f; do
    echo "  ${f#"$SKILL_DIR"/}"
done
echo ""
echo "Next steps:"
echo "  1. Edit SKILL.md description and workflow"
echo "  2. Run: ${PLUGIN_ROOT}/skills/skill-index/scripts/generate-all.sh --force"
echo "  3. Test: invoke $INVOCATION_NAME in Claude Code"
