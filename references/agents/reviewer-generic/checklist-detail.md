# reviewer-generic — Checklist Detail

Depth for the checklist items in
[`.claude/agents/reviewer-generic.md`](../../../.claude/agents/reviewer-generic.md).
The spec carries the numbered items; this file carries what each one
means in practice. Extracted under GH-1197 — the spec's full body loads
into the dispatched session's system prompt on **every** dispatch, and
this is one of the most frequently dispatched agents in the repo.

## 4. Named parameters

Multiline for 3+ args. Only flag truly positional calls — read the
actual code first rather than pattern-matching on the call site.

## 6. FIXME / commented-out code

Verify the PR body explains what changed to make re-enabled code safe.
Re-enabling without that explanation is the finding, not the code.

## 7. Established patterns

Do not question a pattern with 5+ uses in the codebase. A reviewer that
relitigates a settled convention costs more than the convention does.

## 9. Docstring accuracy

When a script documents a guarantee ("always blocks", "never allows"),
verify the implementation covers **all** code paths. For hooks that
parse shell commands: confirm every pipe-chained segment is inspected,
not just `command.split("|")[0]`.

## 9b. Hook guidance alignment

When a new hook pattern is added, verify `session-guidance.md` or
`.claude/rules/*` are updated with the same pattern name, reason, and
alternative. A mismatch between code behaviour and documentation is
what sends a user looking for a rule that does not say what the hook
does.

## 9c. Hook refactoring behaviour equivalence

When a PR modifies the core hook dispatcher (ValidatorChain, filter
logic, exception handling), explicitly verify the new implementation
preserves every observed behaviour of the old:

- a single validator's exception does not prevent subsequent
  validators from running
- validation results are emitted in registration order
- `PermissionDenied` correction short-circuits at the first non-`None`
  result
- `HOOK_DEBUG` logging captures the same details
- disabled/filtered validators are never imported

Compare `hook.py` integration points before and after. Flag as WARNING
if behaviour changes without an explicit justification in the PR body.

## 10. New class without a test suite

When a PR adds a new `.py` file with production logic (classes or
functions), or adds behaviour methods to an existing model, check
whether a corresponding `test_*.py` file exists or is modified in the
same PR. WARNING when missing.

Does NOT apply to: pure data classes / DTOs with no methods, abstract
base classes tested via concrete subclasses, or config/registration
modules.

## 11. Concurrency conventions (GH-827, ADR-0011)

Flag as WARNING when new code diverges from the write-safety model.

**A new shared-state file** — a JSON/YAML store or log under
`~/.config/Dev10x/`, a repo's `.claude/`, or a home cache — written
with a bare `Path.write_text` / `open(…, "w"|"a")` instead of routing
through `dev10x.domain.file_locks`:

- `locked_json_update` / `locked_yaml_update` for a read-modify-write
  cycle — or `file_lock` wrapping a typed load/save when the store
  deserializes to a dataclass rather than a raw dict, as
  `rule_confidence.record_feedback` does
- `atomic_write_text` for a full overwrite
- `atomic_append_line` for an append

A bare load→mutate→save without a lock is a lost-update race; a bare
`write_text` can truncate on crash. When two writers touch the SAME
file, confirm they lock on the same sidecar — `file_lock` appends
`.lock` to the full name while `locked_json_update` replaces the
suffix, so mixing them on one path silently fails to exclude (see the
`file_locks` module docstring).

**A new `subprocess.run` / `subprocess.Popen` call** that omits
`timeout=`. Standalone uv-scripts declare a local
`_SUBPROCESS_TIMEOUT_SECONDS` constant (they cannot import `dev10x`);
in-package code routes through `subprocess_utils`, which bounds the
call already.

## 12. MCP server implementations (`servers/*.py`)

- `plugin.json` includes the server entry; the shebang uses
  `uv run --script`
- every tool is decorated with `@server.tool()`, returns
  `{"error": msg}` on failure, and carries a `-> dict` type hint
- **Return pattern consistency** — verify tools match the pattern
  documented in `.claude/rules/mcp-tools.md`. If a success response
  differs from the examples, flag as WARNING and suggest a docs update.
- **Test plan verification** — flag unchecked items in the PR body; MCP
  servers must be validated to start without errors before merge.
- **Replacement deprecation** — if a tool replaces a Bash fallback,
  require a documented deprecation timeline in `session-guidance.md` or
  a tracking issue.
- **Catalog coverage (GH-1153)** — a new `@server.tool` must ALSO be
  added to `base_permissions` in `skills/upgrade-cleanup/projects.yaml`,
  or named in `enumerate_mcp.WRITE_TOOLS_NOT_SEEDED` when it writes.
  `allowed-tools` front matter and the `mcp-tools.md` table grant
  NOTHING — only the catalog is seeded by `ensure-base`, so an
  un-catalogued read tool prompts on every call, forever.
  `tests/skills/permission/test_catalog_covers_mcp_tools.py` enforces
  this; flag as WARNING if a PR adds a tool without the catalog entry.
