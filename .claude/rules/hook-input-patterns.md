---
paths:
  - "hooks/**"
  - "src/dev10x/hooks/**"
  - "src/dev10x/*/hooks/**"
  - "src/dev10x/core/validators/**"
---

# Hook Input Parsing Patterns

Safe patterns for hooks that parse tool input (JSON, commands, etc.).

## Input Format

PreToolUse hooks receive JSON via stdin with structure:

```json
{
  "tool_input": {
    "command": "...",
    "args": "...",
    ...
  }
}
```

All input is pre-validated by Claude Code, but hooks must handle:
- Malformed JSON gracefully
- Missing/null fields without silent failures
- Parse errors with clear user-visible messages

## Safe Parsing Pattern

```bash
#!/bin/bash
set -euo pipefail

# Read and validate JSON input
INPUT=$(cat) || {
    echo "BLOCKED: Failed to read hook input."
    exit 2
}

# Extract field with explicit empty check
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty') || {
    echo "BLOCKED: Hook input parsing failed (invalid JSON)."
    exit 2
}

# Validate field is non-empty before using
if [[ -z "$COMMAND" ]]; then
    echo "BLOCKED: Missing required field: tool_input.command"
    exit 2
fi

# Safe to use $COMMAND now
if grep -qP 'pattern' <<< "$COMMAND"; then
    echo "BLOCKED: Command contains disallowed pattern."
    exit 2
fi
```

## Anti-Pattern: Silent Defaults

```bash
# ❌ BAD: Empty default drives branching without validation
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
if grep -qP 'pattern' <<< "$COMMAND"; then  # Silent if COMMAND is empty
    exit 2
fi
```

## Error Handling Rules

1. **Parse failures** → exit with code 2, systemMessage describing what failed
2. **Missing fields** → exit with code 2, name the field in error message
3. **Empty values** → test explicitly before branching: `[[ -z "$VAR" ]]`
4. **jq errors** → always use `|| { error_handler; }` not `|| true`

## Examples

### Pattern: Command Validation (validate-pr-base.sh)

```bash
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty') || {
    echo "BLOCKED: Hook input parsing failed."
    exit 2
}
[[ -z "$COMMAND" ]] && {
    echo "BLOCKED: tool_input.command field missing or empty."
    exit 2
}
```

### Pattern: Field Extraction (detect-and-chaining.py)

Python hooks can parse JSON with explicit None checks:

```python
data = json.loads(stdin_input)
command = data.get('tool_input', {}).get('command')
if not command:
    print("BLOCKED: Missing tool_input.command field")
    sys.exit(2)
```

## Testing Hook Input Handling

When writing tests for hooks:

1. **Valid input**: Standard JSON with all required fields
2. **Missing field**: `{"tool_input": {}}` (command omitted)
3. **Empty field**: `{"tool_input": {"command": ""}}`
4. **Malformed JSON**: `{invalid json}`
5. **Non-existent path**: `{"tool_input": null}`

Verify that cases 2–5 all exit with code 2 and produce descriptive systemMessage.
