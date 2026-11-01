---
paths:
  - "hooks/**"
  - "src/dev10x/hooks/**"
  - "src/dev10x/*/hooks/**"
---

# Hook State Schemas

Pattern for documenting and validating JSON state written by hooks for
consumption by other hooks (same session or future sessions).

## When This Pattern Applies

When a hook writes a JSON state object that is intended to be read by:
- Other hooks in the same session (e.g., SessionStart reads what
  SessionStop writes)
- The same hook in a future session (e.g., session state persistence)
- CLI tools that parse persisted state

Examples:
- `session_persist()` writes session state that `session_reload()`
  consumes
- Any hook writing data to `~/.claude/projects/_session_state/`

## Schema Documentation Requirements

When a hook writes JSON state:

1. **Schema definition** — Document all fields in the state object:
   - Field name and type (`str`, `bool`, `list`, etc.)
   - Whether field is optional or required
   - Default value if field is missing
   - Example value

2. **Reader validation** — Grep for all consumers of the schema:
   - Identify every function/hook that reads this state
   - Verify each reader handles all defined fields
   - Verify each reader provides appropriate fallbacks for missing
     fields

3. **Fallback consistency** — For fields with defaults:
   - Document which fields have fallbacks
   - Verify all readers use identical defaults (no silent mismatches)
   - Test behavior when field is missing/null in JSON

4. **Type compatibility** — For hooks implemented in multiple
   languages:
   - Verify Python `bool` serializes to JSON `true`/`false` (not
     string `"true"`)
   - Verify shell scripts parse booleans consistently
   - Test type coercion at language boundaries

5. **Test interop** — When both Python and shell implementations
   exist:
   - Write at least one test that parses output from each language
   - Compare output schemas between implementations
   - Verify identical error handling for missing fields

## Anti-Patterns

- Adding new fields to state without updating readers — causes
  silent failures
- Different fallback values in different readers — inconsistent
  behavior
- Type mismatches between writer and reader (e.g., Python `True`
  vs shell `"true"`) — parsing errors
- Testing only the writer, not the reader — divergence not caught
  until runtime

## Reference

See `.claude/rules/INDEX.md` for hook-related review guidance and
agent routing. Related: `.claude/rules/hook-input-patterns.md`
(input validation).
