# Session Configuration Schema

Schema for `.claude/Dev10x/session.yaml`, read by SessionStart hooks
to configure session behavior.

## File Location

```
~/.claude/Dev10x/session.yaml
```

This file is user-created and persists across sessions. It is not
auto-initialized; users create it when needed to customize friction
levels or activate session modes.

## Schema Definition

| Field | Type | Required | Default | Example |
|-------|------|----------|---------|---------|
| `friction_level` | string (enum) | Yes | `strict` | `adaptive` |
| `active_modes` | list of strings | Yes | `[]` | `[solo-maintainer, open-source]` |
| `allowed_overlays` | list of strings | No | *unset = permissive* | `[]` |

> Since GH-774 the durable keys (`friction_level`, `active_modes`,
> `allowed_overlays`, `gate_*`) live in the sibling **`config.yaml`**;
> `session.yaml` keeps ephemeral per-worktree identity (`branch`,
> `tickets`). `SessionYamlDocument` reads either (config wins, pre-split
> session.yaml is the migration fallback).

### friction_level

Controls how often the agent pauses for user decisions.

| Value | Behavior |
|-------|----------|
| `strict` | Agent pauses frequently; asks confirmation before each major action. Recommended for collaborative work. |
| `guided` | Agent proceeds with confidence but pauses for significant architectural or policy decisions. |
| `adaptive` | Agent operates with high autonomy; pauses only when facing ambiguity that cannot be resolved by the current task context. Recommended for solo-maintainer mode. |

### active_modes

List of named modes that customize agent behavior. Known modes:

| Mode | Behavior | Set by |
|------|----------|--------|
| `solo-maintainer` | Skip reviewer assignment and Slack notifications. Agent assumes single owner and high autonomy. | User (set in session.yaml) |
| `open-source` | Prefer issue templates and public-safe language. Assume external contribution norms. | User (set in session.yaml) |
| `swarm-child` | Internal mode for fanout skill (GH-300+). Agent is part of a swarm and reports to orchestrator. | Skill (set by fanout orchestrator) |

Empty list is valid (no modes active).

### allowed_overlays (GH-805)

Local repo-character allow-list guarding against a **stale/incorrect
high-autonomy mode** being honored where it should not be. It lives in
the gitignored, worktree-copied `config.yaml` — durable between sessions
and copied source→worktree by `post-checkout` (like `.claude`
`settings.local` / `.idea`), but **never committed** to the remote, so
it is a private repo-character preference teammates cannot dispute.

| Value | Behavior |
|-------|----------|
| *unset* (key absent) | Permissive — every session overlay is honored (back-compat). |
| `[]` | No high-autonomy overlay is honored — correct for a **team repo**. A stale `active_modes: [solo-maintainer]` is dropped before gate resolution. |
| `[solo-maintainer]` | Only the listed overlays are honored; any other is dropped. |

The gate resolver (`resolve_gate_for_toplevel`) filters the session's
computed overlays (`solo-maintainer`, `afk`) against this list, dropping
those absent from it — so their `request_review` / `external_notify` /
`merge` skips never apply. Dropping only ever *removes* autonomy, so it
can never make a gate less safe. The `session-mode-guard` SessionStart
feature (`ModeGuardRule`) warns when it drops something.

This is a separate, local tier from the git-tracked
`.dev10x/gate-policy.yaml` project pin (`overrides: {merge: ask}`): the
pin is shared repo policy for specific toggles; `allowed_overlays` is a
private, whole-overlay allow-list.

## Readers (Consumers)

The file read is owned by `SessionYamlDocument`
(`src/dev10x/domain/documents/session_yaml.py`); it returns the parsed
`friction_level` and `active_modes` with soft fallbacks. Policy Rules in
`src/dev10x/domain/session_rules.py` consume those values and perform no
I/O (ADR-0007 D3):

1. **`SessionYamlDocument`** — owns the `session.yaml` read.
   `read_friction_level()`, `read_active_modes()`, and
   `read_friction_and_modes()` apply the fallbacks below.

2. **`BuildAutonomyReassuranceRule`**
   - Receives `friction_level` and `active_modes` as fields
   - Fires only when: `friction_level == "adaptive"` AND `"solo-maintainer"` in `active_modes`
   - Fallback: Silent (returns empty string) if conditions not met
   - Output: Reassurance text displayed at SessionStart

3. **`DecisionGuidanceRule`**
   - Receives `friction_level`
   - Provides guidance text tailored to the selected level

## Fallback Behavior

When fields are missing or malformed:

- **Missing `friction_level`**: Defaults to `"strict"`
- **Malformed `friction_level`** (not in enum): Defaults to `"strict"`, no error
- **Missing `active_modes`**: Defaults to `[]` (empty list, no modes active)
- **Malformed `active_modes`** (not a list): Treated as `[]`, no error
- **Missing entire file**: All defaults apply; session runs in default configuration

All readers handle missing/null fields gracefully — no exceptions are raised.

## Template

Users can create a minimal session.yaml:

```yaml
# ~/.claude/Dev10x/session.yaml
friction_level: adaptive
active_modes:
  - solo-maintainer
```

Or:

```yaml
friction_level: guided
active_modes:
  - open-source
```

## Testing

Verify session.yaml parsing in
`tests/domain/documents/test_session_yaml.py` (file reads + fallbacks)
and rule behaviour in `tests/hooks/test_orchestrators.py` (value-based):

- `TestReadFrictionLevel` — declared / missing / malformed / unknown
- `TestReadActiveModes` — declared / unset / non-list / missing file
- `TestAutonomyReassurance` — fires on adaptive+solo; silent otherwise

## Related Files

- `src/dev10x/domain/friction_level.py` — Friction level enum definition
- `src/dev10x/commands/init.py` — Template initialization
- Skills using `active_modes`: playbook, gh-pr-merge, gh-pr-monitor,
  git-commit, fanout, verify-acc-dod, review
