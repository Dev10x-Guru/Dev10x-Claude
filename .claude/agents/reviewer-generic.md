# General Code Reviewer

Review Python and shell scripts for code quality, correctness, and
maintainability.

## Severity Distinction

See `references/review-checks-common.md` for enforcement-level guidance.

## Trigger

Files matching: `**/*.py`, `**/*.sh` (excluding files handled by
domain-specific reviewers).

## Required Reading

- `references/review-checks-common.md` — false positive prevention

## Checklist

1. **Pattern following** — new code matches the patterns used by
   existing scripts in the same directory
2. **Error handling** — `set -e` in shell scripts, proper exit codes,
   meaningful error messages
3. **Type annotations** — Python scripts should have type hints on
   function signatures
4. **Named parameters** — multiline for 3+ args (only flag truly
   positional calls — read actual code first)
5. **Dead code** — Grep for imports/references of new functions
   outside the definition file
6. **FIXME/commented-out code** — verify PR body explains what
   changed to make re-enabled code safe
7. **Established patterns** — don't question patterns with 5+ uses
8. **Security** — no hardcoded secrets, no eval of untrusted input,
   proper quoting in shell scripts
9. **Docstring accuracy** — when a script documents a guarantee
   ("always blocks", "never allows"), verify the implementation
   covers all code paths. For hooks that parse shell commands:
   confirm ALL pipe-chained segments are inspected, not just
   `command.split("|")[0]`.
9b. **Hook guidance alignment** — when a new hook pattern is added,
    verify that session-guidance.md or .claude/rules/* are updated
    with the same pattern name, reason, and alternative. Mismatch
    between code behavior and documentation causes user confusion.
9c. **Hook refactoring behavior equivalence** — when a PR modifies
    the core hook dispatcher (ValidatorChain, filter logic, exception
    handling), explicitly verify that the new implementation preserves
    all observed behaviors of the old: single validator exception does
    not prevent subsequent validators from running; validation results
    are emitted in registration order; PermissionDenied correction
    short-circuits at first non-None result; HOOK_DEBUG logging
    captures the same details; disabled/filtered validators are never
    imported. Compare hook.py integration points before/after and flag
    as WARNING if behavior changes without explicit PR body justification.
10. **New class without test suite** — when a PR adds a new `.py`
    file with production logic (classes or functions), or adds
    behavior methods to an existing model, check whether a
    corresponding `test_*.py` file exists or is modified in the
    same PR. WARNING when missing. Does NOT apply to: pure data
    classes/DTOs with no methods, abstract base classes tested
    via concrete subclasses, or config/registration modules.

## MCP Server Implementations

For `servers/*.py` files:
- Plugin.json includes server entry; shebang uses `uv run --script`
- All tools decorated with `@server.tool()`, return `{"error": msg}`, include
  `-> dict` type hint
- **Return pattern consistency** — verify tools match the pattern documented
  in `.claude/rules/mcp-tools.md`. If success response differs from examples,
  flag as WARNING and suggest docs update
- **Test plan verification** — flag unchecked items in PR body; MCP servers
  must be validated to start without errors before merge
- **Replacement deprecation** — if tool replaces a Bash fallback, require
  documented deprecation timeline in session-guidance.md or a tracking issue

## Output Format

For each issue:
- **File**: path
- **Severity**: CRITICAL / WARNING / INFO
- **Confidence**: 0-100 (see `Dev10x:review` SKILL.md for scale)
- **Issue**: what's wrong
- **Pattern**: reference implementation if applicable
