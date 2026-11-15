# Micro-Agents (GH-68)

Specs for the two micro-agents the supervisor dispatches from
`instructions.md`: `haiku-ci-poll` (Phase 1) and `haiku-thread-scan`
(Phases 1 and 2).

Two narrow haiku sub-agents replace the prior monolithic background
agent. Each has a minimal tool allowlist, a hard turn budget, no
ability to delegate further, and no ability to mutate state.

**Friction-avoidance preamble (REQUIRED, GH-610):** Both micro-agents
run in fresh subagents that never saw the SessionStart friction
briefing. Before each dispatch, fetch the preamble via
`mcp__plugin_dev10x_cli__background_preamble` and prepend its
`preamble` text to the micro-agent prompt below. The narrow
`allowed_tools` lists are the pre-seeded tool surface — keep them
explicit (do NOT widen to escape a hook block, and never recommend
auto-mode). See `references/orchestration/background-preamble.md`.

## Micro-agent A: haiku-ci-poll

Makes ONE `ci_check_status(wait=true)` call and returns the verdict
JSON. No decision-making, and no loop of its own — the wrapper does
the waiting server-side.

**No poll loop here (GH-1138).** This spec used to be written as a
loop ("if verdict is pending, sleep 30s", plus a "do not continue
past 50 turns" guard), which taught every reader that bespoke
polling is the normal shape. A dispatcher copied it, pointed it at
`gh pr checks` through the `Monitor` tool — which no Dev10x hook
validated at the time — and stalled on a Yes/No prompt. One wrapper
call carries its own poll budget, bounded under the MCP
idle-timeout, so the loop was never needed.

```
subagent_type: "general-purpose"
model: "haiku"
run_in_background: true        # supervisor keeps working
max_turns: 50                  # not 200 — bounded work
description: "Poll CI for PR #{pr_number}"
allowed_tools:
  - mcp__plugin_dev10x_cli__ci_check_status
  - SendMessage                # deliver the verdict (GH-776)
disallowed_tools:
  - Edit, Write, NotebookEdit
  - Bash(git:*), Bash(gh pr ready:*), Bash(gh pr edit:*),
    Bash(gh pr merge:*)
  - Skill(*)                   # cannot delegate further
  - mcp__plugin_dev10x_cli__push_safe
  - mcp__plugin_dev10x_cli__update_pr
prompt: |
  You are a CI-polling micro-agent. Your ONLY job is ONE tool call,
  then delivering its JSON verdict.

  1. Call:
       mcp__plugin_dev10x_cli__ci_check_status(
         pr_number={pr_number}, repo="{repo}", wait=true)

     The wrapper polls server-side on its own budget, kept under the
     ~1800s MCP idle-timeout (GH-808 F2). It returns
     `infra_unavailable` rather than hanging when checks never
     register, and it probes once before sleeping, so a call made
     after CI already finished returns immediately (GH-1088).

     When the supervisor named specific checks to wait out — bot
     legs whose comments the next step would invalidate — pass them
     as `wait_for=["claude-review", "hygiene-review"]`. That keeps
     the wait alive even while a REQUIRED check is red, which is the
     normal state of any branch carrying `fixup!` commits (GH-1138).

  2. Deliver the verdict JSON via
     SendMessage(to="main", summary="ci <verdict>",
     message=<the verdict JSON>). It must be the LAST line of that
     payload — a background agent's bare stdout never reaches the
     supervisor (GH-776).

  You MUST NOT:
    - Write your own poll loop. No `while`, no `until`, no `sleep`,
      through Bash or the Monitor tool. If one call is not enough,
      say so in your report and let the supervisor re-dispatch —
      a hand-rolled loop wedges on a permission prompt that, in an
      unattended run, nobody answers (GH-1138, GH-879).
    - Decide what to do about the verdict — that is the supervisor's
      job.
    - Mark the PR ready, edit anything, comment, or push.
    - Invoke any Skill or further Agent.

  Deliver the verdict JSON via SendMessage(to="main", …) — it must be
  the LAST line of that payload. Do NOT rely on bare stdout; a
  background agent's stdout never reaches the supervisor (GH-776).
```

## Micro-agent B: haiku-thread-scan

Read-only enumerates unresolved review threads, body findings,
and top-level automated comments. Returns structured JSON. No
decision-making, no replies, no state changes.

```
subagent_type: "general-purpose"
model: "haiku"
run_in_background: false       # cheap, run inline
max_turns: 20
description: "Scan PR #{pr_number} threads"
allowed_tools:
  - Bash(gh api graphql:*)
  - Bash(gh api repos/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/check-top-level-comments.sh:*)
  - mcp__plugin_dev10x_cli__check_top_level_comments
disallowed_tools:
  - Edit, Write, NotebookEdit
  - Bash(git:*), Bash(gh pr ready:*), Bash(gh pr edit:*),
    Bash(gh api -X POST:*), Bash(gh api -X PATCH:*),
    Bash(gh api -X DELETE:*)
  - Skill(*)
  - mcp__plugin_dev10x_cli__push_safe
  - mcp__plugin_dev10x_cli__update_pr
prompt: |
  You are a PR-thread-scanning micro-agent. Your ONLY job is to
  enumerate unaddressed review surfaces on PR #{pr_number} and
  return structured JSON. You do not reply, edit, or change state.

  Steps:
    1. GraphQL query reviewThreads where isResolved == false.
       Capture: thread id, first comment author, body, file:line.
    2. Fetch reviews via REST; for each review with a non-empty
       body, detect structured findings (CRITICAL:, BLOCKING:,
       INFO:, **[BLOCKING]**, numbered items with file:line).
       Mark as unaddressed if no top-level PR comment replies
       with `Re:` matching the finding ID.
    3. Call mcp__plugin_dev10x_cli__check_top_level_comments(
       repo="{repo}", pr_number={pr_number}) — do NOT eyeball
       severity yourself. It spans BOTH issue comments AND submitted
       review bodies (flagging bots by account type, known login, or
       HTML marker, GH-743 F2) and returns two structured buckets
       (GH-808 F1): `blocking` (REQUIRED/CRITICAL/BLOCKING) and
       `needs_disposition` (non-blocking INFO/NOTE/SUGGESTION,
       including review-body findings a severity-only scan missed).
       Put `blocking` findings in `top_level_findings` and
       `needs_disposition` findings in `needs_disposition` below. A
       "clean" scan requires BOTH buckets empty — a non-blocking INFO
       still needs an explicit disposition (a `Re:` reply satisfies it).

  Output as the LAST line, single-line JSON:
    {
      "unresolved_threads": [{"id": ..., "author": ..., "path": ..., "body": ...}],
      "body_findings": [{"review_id": ..., "summary": ...}],
      "top_level_findings": [{"comment_id": ..., "summary": ...}],
      "needs_disposition": [{"comment_id": ..., "summary": ...}]
    }

  You MUST NOT:
    - Reply to any thread, even with "acknowledged".
    - Resolve any thread.
    - Edit the PR body or any comment.
    - Invoke any Skill, gh pr ready, or gh api with -X POST/PATCH/DELETE.
    - Speculate on which threads are "actionable" vs not — return
      all unresolved, the supervisor classifies.
```

**Why split into two micro-agents?** CI polling is long-running
and runs in the background while the supervisor works on other
things. Thread scanning is cheap and runs inline so the supervisor
has the result immediately. Combining them would force the cheap
scan to wait for the slow poll.

**Why haiku for both?** Polling and structured enumeration are
mechanical work — no reasoning needed. Haiku is cheap and its
narrow tool list prevents it from doing anything else.

**Anti-pattern (GH-68 incident #2):** Combining the orchestrator
and the poller into one big haiku with `max_turns: 200` and
`mode: dontAsk` is exactly what caused the issue. Do NOT do that.
Each micro-agent has a single observable job and a single-line
JSON output contract.
