# Walk-Away Mode — Contract for Downstream Skills

Defines how skills that emit `AskUserQuestion` consult the
`walk_away` flag set by `Dev10x:afk` and route mid-flight
doubts to the `doubt_sink` instead of pausing.

Companion to `references/friction-levels.md` (which controls
gate behavior universally) and `skills/afk/SKILL.md` (which
sets the flag).

## Config Surface

```yaml
# .claude/Dev10x/session.yaml
friction_level: adaptive
active_modes: [solo-maintainer]
walk_away: true
doubt_sink: pr-description    # pr-description | session-bookmark | commit-footer
```

The four fields together define a "walk-away session." Skills
read all four with one `Read` call and branch on `walk_away`
before classifying the question.

## Question Classification

Skills that call `AskUserQuestion` MUST classify the question
into one of four categories before firing:

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

## Decision Flowchart

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
| `walk_away` | Whether non-destructive gates fire **at all** | this document |
| `doubt_sink` | Where suppressed doubts are logged | this document |

Precedence at a single gate:

1. If question is `destructive` or `blocking` → fire (walk-away off)
2. Else if `walk_away: true` → suppress + log to `doubt_sink`
3. Else if `friction_level: adaptive` and gate has Recommended → auto-select
4. Else → fire normally

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
