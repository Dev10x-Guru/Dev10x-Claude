# Walk-Away Mode — Contract for Downstream Skills

> **ADR-0016 convergence (GH-760).** Gate behavior is now resolved
> by the `resolve_gate` tool (`dev10x.domain.gate_policy`), not by
> skills reading `walk_away` and hand-classifying each question.
> `Dev10x:afk` composes the walk-away posture as `gate_preset:
> adaptive` + `gate_overlays: [afk]`; the `afk` overlay carries
> `session_adoption: auto-advance` and `doubt_sink: pr-description`.
> **`walk_away` is deprecated** — the resolver's `legacy_session_mapping`
> still reads a `walk_away: true` on an un-migrated `session.yaml` and
> maps it to the `afk` overlay (read-compat), but `Dev10x:afk` no
> longer writes it and no skill should hand-roll the classification
> below. This document is retained for the `doubt_sink` contract
> (still a live overlay toggle) and as background on the pre-resolver
> model. For current gate behavior, see
> `references/friction-levels.md` § Plan-Approval Gate.

Companion to `references/friction-levels.md` (which controls
gate behavior universally) and `skills/afk/SKILL.md` (which
composes the preset + overlay).

## Config Surface

```yaml
# .claude/Dev10x/session.yaml — current (ADR-0016)
gate_preset: adaptive         # walk-away base
gate_overlays: [afk]          # session_adoption: auto-advance + doubt_sink
```

```yaml
# .claude/Dev10x/session.yaml — legacy (read-compat only, deprecated)
friction_level: adaptive
active_modes: [solo-maintainer]
walk_away: true
doubt_sink: pr-description    # pr-description | session-bookmark | commit-footer
```

The resolver reads the new-style keys directly; a legacy file is
mapped to `(preset, overlays)` by `legacy_session_mapping` before
resolution. `doubt_sink` remains a real toggle — it is supplied by
the `afk` overlay (default `pr-description`) and read from the
resolver's resolved policy, not hand-parsed by each skill.

## Question Classification (superseded by resolver floors)

> The four-class manual classification below is **superseded**: the
> `resolve_gate` resolver now performs the equivalent decision. The
> `destructive` and `blocking` classes map to the resolver's **safety
> floors** (`destructive_irreversible`, `secret_access`,
> `cross_author_push`, `privacy_disclosure`, `blocking`), which force
> `ask` regardless of preset. The `strategy` / `informational` classes
> map to preset auto-advance under the `adaptive` base + `afk` overlay.
> Skills pass the concrete facts (author type, destructiveness,
> blocking) as `context` to `resolve_gate` and honor the returned
> `effect` — they do not hand-classify. The table is retained to show
> how the historical classes correspond to resolver behavior.

Historical four-category model (pre-resolver):

| Class | Examples | Walk-away behavior |
|-------|----------|---------------------|
| `destructive` | Force-push to protected branch, mass file delete, `aws-vault` secret retrieval, `git reset --hard origin/main` | **Fire normally** (ALWAYS_ASK) |
| `blocking` | No auth credentials, conflicting upstream merge, missing required ADR, MCP server unreachable | **Fire normally** — the supervisor must intervene |
| `strategy` | "Bundle or split PRs?", "Fixup or full restructure?", "Which milestone?" | **Suppress, pick Recommended, log to doubt_sink** |
| `informational` | "Which slug?", "Add this nit to PR?", "Confirm title?" | **Suppress, pick best-guess, log to doubt_sink** |

Re-strategy questions (asking the same strategy a second time
mid-execution) are always `strategy`-class. The first prompt may
have fired before walk-away was enabled; the second MUST be
suppressed.

## Decision Flowchart (legacy — pre-resolver)

The flowchart below is the pre-ADR-0016 model, kept for context.
Today a skill calls `resolve_gate` and branches on the returned
`effect` (see § Relationship to Friction Levels for the current
pipeline).

```
AskUserQuestion call site
  │
  ▼
Read .claude/Dev10x/session.yaml
  │
  ▼
walk_away == true ?
  ├── no → fire AskUserQuestion (existing adaptive/guided/strict rules apply)
  └── yes
        │
        ▼
   Classify question
        ├── destructive → fire AskUserQuestion (ALWAYS_ASK)
        ├── blocking    → fire AskUserQuestion (cannot proceed)
        ├── strategy    → pick Recommended, log to doubt_sink
        └── informational → pick best-guess, log to doubt_sink
```

## doubt_sink Targets

The `doubt_sink` field controls where suppressed-doubt entries
land. Skills append, never overwrite.

### `pr-description` (default)

Append to the active PR body under a dedicated header. If no
PR exists yet, buffer the entries in session state and flush
them when `Dev10x:gh-pr-create` runs.

```markdown
## Concerns surfaced during implementation

- [walk-away] Considered splitting commit 4 (auth refactor) into a
  separate PR; proceeded with bundle to match approved strategy.
  Recommended option: "keep in bundle".
- [walk-away] Test coverage on `RetryHandler.backoff` is 0%; added
  TODO instead of writing tests this PR. Followup: GH-???.
```

Each entry includes:
- A `[walk-away]` tag so reviewers can grep
- The doubt in one sentence
- What the agent did instead (the Recommended option taken)
- Optional pointer to a followup ticket

### `session-bookmark`

Append to the PR bookmark comment created by
`Dev10x:gh-pr-bookmark`. Use for doubts that should survive
session boundaries but do not belong in the merged PR body.

### `commit-footer`

Append to the most recent commit message as a `Concerns:` footer.
Use only when the doubt is commit-scoped, not PR-scoped.

## Skill Integration Checklist

For a skill that emits `AskUserQuestion`:

1. ✓ Read `.claude/Dev10x/session.yaml` before the gate
2. ✓ Skip the read if `walk_away` is already known in scope
3. ✓ Classify the question into one of four classes
4. ✓ When suppressing, call the same code path that handles the
     Recommended option at `adaptive` friction
5. ✓ Append a one-line entry to the configured `doubt_sink`
6. ✓ Log the suppression to the audit hook so `Dev10x:skill-audit`
     can surface "walk-away suppressions" in the session report

## Relationship to Friction Levels

| Layer | Controls | Source of truth |
|-------|----------|----------------|
| `friction_level` | How gates with a `(Recommended)` option resolve | `references/friction-levels.md` |
| `active_modes` | Which playbook steps exist | `references/execution-modes.md` |
| `gate_overlays: [afk]` | Trusts a stale session + sets `doubt_sink` | `presets/friction/overlays/afk.yaml` |
| `doubt_sink` | Where suppressed doubts are logged | the `afk` overlay (this document documents the sinks) |

Precedence at a single gate is the **resolver pipeline** (ADR-0016
D-4), not the legacy walk-away branch — see
`references/friction-levels.md` § Plan-Approval Gate:

1. Safety floors (destructive+irreversible, blocking, secret access,
   cross-author, privacy disclosure) → `ask` (deny-overrides)
2. Else the resolved toggle from `gate_preset` + `gate_overlays` +
   project pin + session `gate_overrides` decides
   `ask` / `auto-advance` / `skip`
3. On `auto-advance`, the resolver's `record` line is logged to
   `doubt_sink` so a present supervisor can still veto

## Anti-Patterns

- **Classifying every gate as `blocking` to keep the prompt** —
  defeats walk-away. Reserve `blocking` for upstream/auth/credential
  failures the supervisor cannot fix later.
- **Logging to `commit-footer` when the doubt is PR-wide** —
  commit footers should be commit-scoped; cross-commit concerns
  belong in the PR body.
- **Silent suppression** — every suppressed gate MUST log to
  `doubt_sink`. A gate that was suppressed without a log entry
  is indistinguishable from a bug.

## Known Failure Modes (Pre-Walk-Away)

These are the recurring failures walk-away mode addresses,
documented from user feedback memory:

- `feedback_adaptive_no_pre_approval_gates` — adaptive still
  fires gates that have no Recommended option
- `feedback_ambient_chatter_not_pause_signal` — agent treats
  the user's `[USER PASTED A SLACK SNIPPET]` chatter as a
  reason to pause; walk-away forces push-through
- `feedback_solo_maintainer_pr_loop` — solo-maintainer mode
  loops waiting for reviewer assignment; walk-away short-circuits
- `feedback_no_restrategy_after_user_chose` — agent re-prompts
  for a strategy already chosen in Phase 3; walk-away suppresses
  the duplicate prompt and logs the doubt to the PR body

## Out of Scope (Followups)

These are deliberate gaps the MVP `Dev10x:afk` skill does not close:

- **Automatic classification of arbitrary `AskUserQuestion` calls**
  by static analysis — each emitting skill must classify its own
  questions
- **Retroactive cancellation** of an `AskUserQuestion` already in
  flight — walk-away takes effect on the next gate
- **doubt_sink: slack** — Slack-routed doubts are a candidate
  followup; today the three sinks (pr-description, session-bookmark,
  commit-footer) cover the documented use cases
