# 9. Result[T] contract at the MCP boundary

Date: 2026-05-30

## Status

Accepted

## Context

MCP tools in this plugin follow a two-layer pattern (see
`.claude/rules/mcp-tools.md`): internal functions return a typed
`Result[T]` (`SuccessResult[T] | ErrorResult` from
`dev10x.domain.common.result`), and the `@server.tool()` handler at
the MCP boundary calls `.to_dict()` to produce the wire-format dict.

### Current State

`SuccessResult.to_dict()` branches on the runtime type of its value:

```python
def to_dict(self) -> dict[str, Any]:
    if isinstance(self.value, dict):
        return self.value          # tool-specific fields, raw
    return {"value": self.value}   # scalar/list, wrapped
```

The ~40 tools that wrap a dict (`ok({"path": ...})`,
`ok(json.loads(...))`, `ok(parse_key_value_output(...))`) get their
dict back verbatim — this is the documented "tool-specific fields"
wire format. A small number of callers pass non-dict values
(`ok("")` ×3, `ok(json.loads(...))` where the JSON is an array) and
receive `{"value": ...}` instead.

### Problems

1. **Silent shape polymorphism (A4).** `to_dict()` returns two
   structurally different shapes depending on a runtime
   `isinstance` check. Callers cannot statically know whether they
   get `{...fields}` or `{"value": ...}`; the branch is invisible at
   the call site and untested as a contract.
2. **Bypassed boundary (H1 + I9).** The `record_upgrade` MCP handler
   returns a raw dict directly, never constructing a `Result[T]` —
   the single outlier across ~40 handlers, so the contract is "true
   by convention" rather than enforced.
3. **No type-checkable contract (B5).** Nothing asserts that an
   object crossing the MCP boundary actually satisfies the
   `to_dict() -> dict` shape. A handler that forgets `.to_dict()`
   (returning a `Result` object, a `CompletedProcess`, etc.) fails
   only at serialization time, far from the cause.

### Prerequisites

This ADR must be accepted **before** the A4 + B5 implementation
lands — the uniform-shape choice is breaking-change-adjacent
(it governs the wire format of every MCP tool consumer). Tracked by
GH-243 (Audit-2026-05-18 Milestone 4). Source:
`docs/memos/005-2026-05-18-architecture-audit.md` § 5.

## Decision

We will make the `SuccessResult` wire shape **uniform and
non-polymorphic**: `SuccessResult.value` is contractually a
`Mapping[str, Any]`, and `to_dict()` returns it unchanged. We will
introduce a `@runtime_checkable ResultProtocol` that the MCP
boundary can assert against.

### New Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| `ResultProtocol` | `src/dev10x/domain/common/result.py` | `@runtime_checkable` Protocol declaring `to_dict(self) -> dict[str, Any]`; both result types satisfy it |
| `record_upgrade()` | `src/dev10x/domain/install_version.py` | Domain function returning `Result[dict]`; the MCP handler becomes a thin `.to_dict()` wrapper (H1 + I9) |

### Code Examples

```python
# src/dev10x/domain/common/result.py

@runtime_checkable
class ResultProtocol(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SuccessResult[T]:
    value: T  # contract: T is a Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.value)
```

The `isinstance(self.value, dict)` branch is removed. A codebase
audit found the **entire** non-dict `ok()` surface is three internal
validator sentinels (`ok("")` in `validators/sql_safety.py` ×2 and
`validators/commit_jtbd.py` ×1) — pure pass/block signals whose value
carries no payload and which never reach `.to_dict()`. They migrate
to `ok({})`. Every other `ok(...)` site (including all `gh api` /
`json.loads` handlers, typed `Result[dict[str, Any]]`) already passes
a dict, so the wire format is preserved exactly — no MCP consumer
changes.

The MCP boundary asserts the contract once, centrally:

```python
# at the @server.tool() seam
result = await internal_fn(...)
assert isinstance(result, ResultProtocol)  # type-safety guard
return result.to_dict()
```

## Alternatives Considered

### Alternative 1: Always wrap — `to_dict()` returns `{"value": self.value}`

Drop the dict branch and wrap *everything*.

**Pros:**
- Trivially uniform; no caller migration of non-dict values.

**Cons:**
- Breaks **every** dict-returning tool: `{"path": "/tmp"}` becomes
  `{"value": {"path": "/tmp"}}`. ~40 handlers plus all skill/test
  consumers would need rewriting.
- Discards the documented "tool-specific fields" wire format that
  callers already branch on (`"error"` key vs payload).

**Verdict:** Rejected — maximally breaking for the common case to
accommodate the rare one.

### Alternative 2: Keep the polymorphic branch

Status quo.

**Pros:**
- Zero migration.

**Cons:**
- The finding itself: silent, untested, statically-invisible shape
  switching. Leaves B5 (no protocol) and the boundary unenforced.

**Verdict:** Rejected — this is the problem being solved.

### Alternative 3 (Selected): value is always a Mapping; `to_dict()` returns it raw

**Pros:**
- **Zero change** for the ~40 dict-returning tools — the wire format
  they already emit is preserved exactly.
- One shape, statically knowable; the `isinstance` branch is gone.
- `ResultProtocol` makes the boundary contract type-checkable and
  `@runtime_checkable` for an explicit assertion.
- Migration is confined to the few non-dict callers (small, S-sized).

**Cons:**
- Non-dict callers (`ok("")`, array payloads) must be migrated to
  pass a dict — a one-time, mechanical change.

**Verdict:** Selected — least-breaking, removes the polymorphism, and
the wire format matches the documented contract.

## Consequences

### What Becomes Easier

1. MCP consumers branch only on the presence of an `"error"` key; a
   success payload is always the tool-specific dict — no `{"value":
   ...}` special case to anticipate.
2. New tools have one obvious rule: `ok()` takes a dict. The
   `ResultProtocol` assertion catches a forgotten `.to_dict()` at the
   boundary instead of at JSON-encode time.
3. `record_upgrade` joins the uniform pattern, so the "~40 handlers,
   1 outlier" caveat in `.claude/rules/mcp-tools.md` disappears.

### What Becomes More Difficult

1. Callers may no longer return a bare scalar or list from `ok()`;
   they must choose a field name. This is a deliberate constraint,
   not an accident.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| A non-dict `ok()` caller is missed and silently changes shape | Medium | Medium | Grep every `ok(` site during implementation; add a unit test asserting `to_dict()` returns the input mapping unchanged; the removed branch means a non-Mapping value now raises in `dict(self.value)` rather than silently wrapping |
| Wire-format regression for a tool a skill depends on | Low | Medium | Selected option preserves the dict path verbatim; full test suite (incl. skill/integration tests) must pass before merge |
| `@runtime_checkable` Protocol only checks method presence, not signature | Low | Low | Documented limitation of `runtime_checkable`; the assertion guards the common "forgot `.to_dict()`" mistake, which is the intended scope |

## Implementation Plan

Shipped together under GH-243 (one PR, atomic commits):

### Phase 1: Contract (this ADR)

1. `src/dev10x/domain/common/result.py` — add `@runtime_checkable
   ResultProtocol`; remove the `isinstance` branch from
   `SuccessResult.to_dict()` (A4 + B5).
2. Migrate non-dict `ok()` callers to pass a Mapping; add a
   `to_dict()` round-trip unit test.

### Phase 2: Boundary outliers

3. `src/dev10x/domain/install_version.py` — extract
   `record_upgrade() -> Result[dict]`; the `@server.tool()` handler
   becomes a `.to_dict()` wrapper (H1 + I9).
4. `_gh_api` returns `Result[dict[str, Any]]` (calling
   `_parse_gh_api_result` internally) so the contract is enforced in
   one place instead of 20+ call sites (I8).

### Phase 3: Maintainability (mechanical, no contract change)

5. Split `mcp/server_cli.py` (~1834 lines) into domain modules
   (`mcp/github_tools.py`, `mcp/git_tools.py`, `mcp/plan_tools.py`,
   …); a thin `server_cli.py` composes them (A6).

## References

### Internal References

- [GH-243](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/243) —
  Audit-2026-05-18 M4: MCP Contract Hygiene
- Audit memo: `docs/memos/005-2026-05-18-architecture-audit.md` § 5
- [ADR-0006](0006-keep-internal-github-mcp-over-official-server.md) —
  Keep internal GitHub MCP over official server
- MCP tool contract: `.claude/rules/mcp-tools.md`
