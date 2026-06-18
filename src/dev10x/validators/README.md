# Validators

Bash-command validators for Claude Code hooks. Each validator inspects a
`HookInput` and decides whether to block, allow, or abstain (PreToolUse),
and optionally how to correct a denied command (PermissionDenied).

## Architecture

The package is built from three named design patterns. Naming them keeps
the short-circuit-vs-accumulate and add-a-filter decisions legible to
contributors.

| Pattern | GoF / PoEAA | Class | Role |
|---|---|---|---|
| Chain of Responsibility | GoF | `ValidatorChain.correct` | First validator returning a `HookRetry` wins — short-circuits the chain. |
| Chain of Responsibility (accumulating variant) | GoF | `ValidatorChain.run` | Every applicable validator may emit a result; iteration continues so multiple validators speak. |
| Strategy | GoF | `ValidatorFilter` (`ProfileFilter`, `DisableListFilter`, `ExperimentalFilter`) | Interchangeable `keep(spec)` predicates the registry applies at build time; new filtering policy = new strategy. |
| Template Method | GoF | `ValidatorBase` | Declares the `should_run → validate` gate and the `rule_id`/`profile`/`experimental` metadata contract subclasses fill in. |

`ValidatorRegistry` owns the `ValidatorSpec` list, applies the active
`ValidatorFilter` strategies before importing any validator module
(lazy import), and verifies each class's declared metadata matches its
spec at registration time.

### Choosing a chain variant

When adding a validator, pick the path by intent:

- **Pre-emptive** (must stop other validators from speaking) → implement
  `correct()` so it joins the short-circuit `ValidatorChain.correct`
  path.
- **Independent opinion** (one of several voices) → implement
  `validate()`; it joins the accumulating `ValidatorChain.run` path.

### Adding a filter

Write a new `@dataclass(frozen=True)` implementing the `ValidatorFilter`
Protocol's `keep(spec) -> bool`, then add it to the `filters` list passed
to `ValidatorRegistry`. No registry changes are required — that is the
point of the Strategy boundary.

## Profile tiers and rule IDs

See `.claude/rules/hook-patterns.md` § Profile Tiers for the
`minimal`/`standard`/`strict` tier assignments and the `DXNNN` rule-ID
table.
