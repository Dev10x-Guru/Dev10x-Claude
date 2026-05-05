# Task Orchestration Patterns

Shared reference for skills that manage multi-step workflows.
Skills reference this index; per-pattern detail files in
`references/orchestration/` load on demand.

## Universal Rules (apply to ALL skills)

- **Auto-advance** — complete a step, immediately start the
  next. Never pause to ask "should I continue?". Queue genuine
  A/B decisions and batch them at interrupt time. See
  [`orchestration/auto-advance.md`](orchestration/auto-advance.md).
- **Mandatory task tracking** — every skill MUST use `TaskCreate`,
  even single-step skills. Nested-mode exemption applies when
  invoked by a parent orchestrator. See
  [`orchestration/task-tracking.md`](orchestration/task-tracking.md).

## Patterns

| Pattern | Purpose | Detail file |
|---------|---------|-------------|
| 1 + 2 | Out-of-order execution and plan mutation | [`orchestration/plan-mutation.md`](orchestration/plan-mutation.md) |
| 3 | `AskUserQuestion` for decisions | [`orchestration/decision-gates.md`](orchestration/decision-gates.md) |
| 4 | Subagent dispatch, wave orchestration, fanout, permission-aware dispatch | [`orchestration/subagent-dispatch.md`](orchestration/subagent-dispatch.md) |
| 4a | Subagent status protocol (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED) | [`orchestration/subagent-status-protocol.md`](orchestration/subagent-status-protocol.md) |
| 5 + 6 + 7 | Teams and orchestration templates | [`orchestration/teams-and-templates.md`](orchestration/teams-and-templates.md) |
| 8 | Progress compaction for long runs | [`orchestration/compaction.md`](orchestration/compaction.md) |
| 9 | Task reconciliation after delegation + script operations map | [`orchestration/reconciliation.md`](orchestration/reconciliation.md) |

## When skills reference this document

Skills typically include a line like:

> This skill follows `references/task-orchestration.md` patterns.

That linkage covers the universal rules above. Skills that lean
on a specific pattern should link the pattern file directly:

> See `references/orchestration/subagent-dispatch.md` for the
> full dispatch pattern.

## When to skip pattern docs

Minimal-tier skills (1-2 steps, no decisions) only need
auto-advance and task-tracking. They do NOT need to read the
pattern detail files.

Full-tier skills (4+ phases, decisions, parallelism) should
load the pattern files they rely on — not all of them.
