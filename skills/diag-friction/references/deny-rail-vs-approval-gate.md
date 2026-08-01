# Approved in-session, denied at the permission layer

The scenario where an `AskUserQuestion` gate returns "yes" and the
command is *still* refused — and why the correct response is to hand
the command to the human rather than to find another spelling.

## The shape

Two independent authorities have to agree before a command runs:

| Authority | Question it answers | Where it lives |
|---|---|---|
| In-session approval gate | "Does the supervisor want this action?" | `AskUserQuestion` in the current turn |
| Permission layer | "Is this command shape permitted at all?" | `deny` rules in settings, plus PreToolUse hooks |

An `AskUserQuestion` answer is **consent to the intent**. It is not a
permission grant, and it cannot be one — the gate runs inside the
conversation, while the deny rule is evaluated by the harness on the
tool call. So "the supervisor said yes" and "the command is refused"
are perfectly consistent states, not a contradiction to resolve.

Field case (GH-972 F4): a working-copy cleanup was approved through an
`AskUserQuestion` gate; the `git checkout --` call was then refused by
a global deny rule — a deliberate rail against agents discarding
uncommitted work. It happened twice in one session.

## Why "find another command" is the wrong instinct

The reflex after a denial is to reach for a synonym. Here that reflex
defeats the rail:

| Refused | Tempting substitute | Why it is worse |
|---|---|---|
| `git checkout -- <path>` | `git restore <path>` | Same destructive effect; the rail exists to protect the *outcome*, not the spelling |
| `git checkout -- <path>` | `git stash` / `git stash drop` | Discards the same work with an extra step and no audit trail |
| any denied write | a hand-rolled equivalent (`rm` + re-checkout, editor round-trip) | Launders a denied operation through shapes the rail was never written to catch |

A deny rule is a **standing decision by the supervisor**, taken while
awake and applied to a class of actions. An in-session "yes" to one
instance does not overturn it, and an agent that routes around it has
substituted its own judgment for the supervisor's. This is the same
family as the `bypassPermissions` footgun (Step 3e / GH-310): both
trade a durable guardrail for one unblocked turn.

## The correct response

1. **Stop.** Do not retry, do not re-spell, do not edit settings.
2. **State the split plainly**: the action was approved, the command
   shape is denied by a standing rule, and the two are different
   authorities.
3. **Hand the exact command to the human**, ready to paste — including
   the working directory it must run in. In an interactive session the
   supervisor runs it via the inline-shell prefix; that is the
   sanctioned path and takes seconds.
4. **Continue with everything the denial does not block.** A refused
   cleanup rarely blocks the actual deliverable; treat it as one item
   handed back, not as a stopped workflow.
5. **Do NOT propose an allow-rule for the denied shape.** Steps 3b/3d
   generalize rules for *unmatched* commands; a command matched by an
   explicit `deny` is a decision, and reopening it is the supervisor's
   call to raise, not the agent's to propose mid-task.

## Unattended runs

There is no human to hand it to. Then:

- Record the blocked command and its intent in the run's decision log
  (`DECISIONS.md`) as a supervisor item for the morning.
- Route around the *need*, never around the rule — e.g. a dirty tree
  that cannot be discarded can usually be left dirty on a branch
  nobody else touches, or the work can move to a fresh worktree.
- If the deny rule genuinely blocks a whole class of sanctioned work,
  that is structural friction: file it upstream per Step 3c rather
  than improvising a spelling at 03:00.

## What this is NOT

This is not the "chaining shifted the prefix" case (Step 3b) or the
"no allow rule exists yet" case (Step 3d). Those are *matching* gaps,
where a simpler pre-approved form is the right answer. Here the rule
matched exactly what it was written to match, and it worked.
