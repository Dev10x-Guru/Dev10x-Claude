# Required File Modifications for Lessons Learned PR #382

## File: `.claude/rules/script-domain-boundaries.md`

### Change 1: Add Exception Section (BEFORE Reviewer Checklist)

**Location:** Insert after line 43 (after "A genuinely-unknown state..." paragraph)  
**Content to add:**

```markdown
### Exception: Config Loaders at Critical Path

Config helper functions (e.g., `dev10x.skills.permission.config::resolve_config`)
may call `sys.exit(1)` on missing or invalid configuration **only** when all of:

1. The function has exactly one call chain: CLI entrypoint → single domain
   module → config loader. Multiple callers indicate the error should be
   returned as `Result[T]` instead.
2. Missing config is unrecoverable (user must create/fix the file before
   retrying).
3. The exception is documented in the module's docstring.

This exception is narrow: do not generalize it to other helper functions.
General utilities shared across multiple call chains must use `Result[T]`.
```

### Change 2: Expand Reviewer Checklist (REPLACE lines 45–51)

**Old checklist:**
```markdown
## Reviewer checklist

- Domain function uses `logging`, returns `Result[T]`, no `sys.exit`,
  no `print()`.
- Script `main()` owns exit codes and printed output.
- A stdout-parsed script emits errors as JSON on stdout, exits
  non-zero.
```

**New checklist:**
```markdown
## Reviewer checklist

1. **Logging module usage** — Domain function imports and uses `logging`
   module (e.g., `logging.error()`, `logging.warning()`), not `print()` or
   `stderr.write()`.
2. **Result[T] type annotation** — Domain function return type is
   explicitly annotated as `Result[T]` (e.g., `-> Result[dict[str, Any]]`),
   not bare `-> dict | None` or void.
3. **No process exit** — Domain function does not call `sys.exit()`,
   `exit()`, or `raise SystemExit`.
4. **Helper-function scope** — Functions called from ≥2 callers in
   different modules must not call `sys.exit()`. If one caller needs to
   exit on error, the exit must occur in the caller, not the helper.
5. **Script entry point** — Script's `main()` function owns process exit:
   it maps domain function results to `sys.exit(N)` with a stderr message.
6. **Stdout-parsed script errors** — When a script's stdout is parsed (e.g.,
   JSON verdict), errors must be emitted as JSON on stdout (not stderr) and
   the script must exit non-zero, so the consumer parses one channel.
```

## Summary

- **Current file size:** 51 lines
- **New file size:** ~75 lines (within 200-line budget)
- **Lines added:** ~24
- **Files modified:** 1

## Application Instructions

Once permissions are approved, apply changes using any of:

1. **Manual edit in editor** — Copy both changes above into the file
2. **Git checkout + edit** — Edit the file and `git add` it
3. **Script application** — Run the prepared Python script at `/tmp/update_rules.py`

Then proceed with: `git add .claude/rules/script-domain-boundaries.md && git commit ...`
