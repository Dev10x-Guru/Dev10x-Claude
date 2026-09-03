# Walk-Away — the `afk` overlay and the doubt sink

Contract for skills running while nobody is at the keyboard.
`Dev10x:afk` composes the walk-away posture as the baseline preset
plus `gate_overlays: [afk]`; the overlay carries
`session_adoption: auto-advance` (trust a stale session) and
`doubt_sink: pr-description` (route deferred decisions to the PR
body).

Companion to `references/friction-levels.md`, which owns how a gate
resolves. This document owns the `doubt_sink` contract.

**There is no separate suppression layer and no `walk_away` flag.**
Gate suppression is just the baseline auto-advancing every non-floored
toggle ([ADR-0022](../docs/adr/0022-single-baseline-gate-model-with-supervisor-review.md)
D-1); `afk` adds only the two toggles above (D-6 leaves the overlay
otherwise untouched). Nothing writes `walk_away`, and no skill may
branch on it — `dev10x config migrate-schema` converts an old
`walk_away: true` into the `afk` overlay it always meant.

## Config surface

```yaml
# ~/.config/Dev10x/friction.yaml
projects:
  - match: ["*/<repo>", "*/<repo>-*"]
    gate_overlays: [afk]      # session_adoption + doubt_sink
    supervisor_review: none   # only if the supervisor really is out
```

`doubt_sink` is a real toggle supplied by the overlay (default
`pr-description`). Read it from the resolver's resolved policy — it
comes back as `log_to` on every `resolve_gate` answer — rather than
parsing the config in each skill.

Note what `afk` does **not** buy: it is a statement that no human is
present to answer a widget, which is orthogonal to *who reads the PR*.
`supervisor_review: required` still floors the review gate, and an
unattended run will park there. That is the intended behaviour — see
`references/friction-levels.md` § `supervisor_review` for the remedy
(the `review:cleared` label, or the durable key).

## Which questions still fire

Skills do not classify their own questions. They pass the concrete
facts about the instance as `resolve_gate` `context` and honour the
returned `effect`. The two classes that used to be hand-labelled map
onto the resolver as follows:

| Historical class | Today |
|---|---|
| `destructive`, `blocking` | Safety floors (`destructive_irreversible`, `secret_access`, `cross_author_push`, `privacy_disclosure`, `blocking`) — `ask` regardless of overlay |
| `strategy`, `informational` | Auto-advance, logged to `doubt_sink` |

Re-asking a strategy already chosen is never a floor: the first prompt
may have fired before the supervisor left, and the second must
auto-advance.

## `doubt_sink` targets

Where suppressed-doubt entries land. Skills append, never overwrite.

### `pr-description` (default)

Append to the active PR body under a dedicated header. If no PR exists
yet, buffer the entries and flush them when `Dev10x:gh-pr-create`
runs.

```markdown
## Concerns surfaced during implementation

- [walk-away] Considered splitting commit 4 (auth refactor) into a
  separate PR; proceeded with the bundle to match the approved
  strategy. Recommended option: "keep in bundle".
- [walk-away] Test coverage on `RetryHandler.backoff` is 0%; added a
  TODO instead of writing tests this PR. Followup: GH-???.
```

Each entry carries a `[walk-away]` tag so reviewers can grep, the
doubt in one sentence, what the agent did instead, and optionally a
pointer to a followup ticket.

### `session-bookmark`

Append to the PR bookmark comment created by `Dev10x:gh-pr-bookmark`.
Use for doubts that should survive session boundaries but do not
belong in the merged PR body.

### `commit-footer`

Append to the most recent commit message as a `Concerns:` footer. Use
only when the doubt is commit-scoped, not PR-scoped.

## Skill integration checklist

For a skill that emits `AskUserQuestion`:

1. ✓ Call `mcp__plugin_Dev10x_cli__resolve_gate(gate=…)` before the
     gate — do NOT read a config file and classify by hand; the
     resolver owns floor / overlay / project-pin precedence, and
     re-deriving it drifts (GH-760)
2. ✓ Branch on the returned `effect` (`ask` / `auto-advance` / `skip`)
3. ✓ On `auto-advance`, call the same code path that handles the
     recommended option, and surface the returned `record` line so a
     present supervisor can still veto
4. ✓ Append a one-line entry to the resolved `log_to` doubt sink
5. ✓ Log the suppression to the audit hook so `Dev10x:skill-audit`
     can surface walk-away suppressions in the session report

## Anti-patterns

- **Claiming a gate is `blocking` to keep the prompt** — that defeats
  walk-away. Reserve `blocking` for upstream/auth/credential failures
  the supervisor cannot fix later.
- **Logging to `commit-footer` when the doubt is PR-wide** — commit
  footers are commit-scoped; cross-commit concerns belong in the PR
  body.
- **Silent suppression** — every auto-advanced gate MUST log its
  `record` line to `doubt_sink`. A gate suppressed without a log entry
  is indistinguishable from a bug (ADR-0016 D-7).

## Known failure modes this addresses

Recurring failures documented from supervisor feedback:

- The agent stops at a gate that has no recommended option
- The agent treats ambient chatter (a pasted Slack snippet) as a
  reason to pause
- A solo-maintainer PR loop spins waiting for a reviewer assignment
  that is never coming
- The agent re-prompts for a strategy the supervisor already chose

## Out of scope

Deliberate gaps the `Dev10x:afk` skill does not close:

- **Retroactive cancellation** of an `AskUserQuestion` already in
  flight — the overlay takes effect at the next gate
- **`doubt_sink: slack`** — a candidate followup; the three sinks
  above cover the documented use cases
