# Phase 3, 3.5 and 3.6: Notification and Post-Merge

## Phase 3: Notification (REQUIRES USER CONFIRMATION)

**CRITICAL: Do NOT post notifications without resolving the gate
first.**

Phase 3's notification step calls `resolve_gate(gate=
"external_notify")` (Step 2 below) and branches on the returned
`effect`. The resolver — not this skill — decides whether to
ask, auto-advance, or skip, based on session policy (preset,
overlays, including the solo-maintainer overlay). Do NOT
special-case `friction_level` or `active_modes` in prose here.

### Step 0: Verify PR state via MCP

**Hard rule: Verify final PR state with the MCP tool — NEVER use
raw `gh pr view` or `gh pr checks`.**

`mcp__plugin_dev10x_cli__verify_pr_state(pr_number={pr_number})`

Parse `is_draft`, `state`, `review_decision`, and `checks_passing`
from the response. Only proceed to notification if checks pass and
no blocking issues.

### Step 1: Prepare

Gather PR info, count open threads, verify readiness.

**Primary (MCP tool):** Call `mcp__plugin_dev10x_cli__pr_notify`
with `pr_number={pr_number}`, `repo={repo}` and `action="prepare"`.

**Fallback (script):** Only when the MCP server is unavailable:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  prepare --pr {pr_number} --repo {repo}
```

If `open_threads > 0`, verify the count using GraphQL `isResolved`
(see "Counting Unaddressed Comments" in Phase 2). Only return to
Phase 2 if unresolved threads actually exist — `prepare` may
count resolved threads as open if it uses the REST API.

*Why?* Reviewers should only be pinged when the PR is fully ready.

### Step 2: Resolve notification gate

Call `mcp__plugin_dev10x_cli__resolve_gate(gate="external_notify",
context={})`.

1. `effect == "ask"` → Fire the EXISTING `AskUserQuestion` widget:
   - Question: "PR #{pr_number} is ready for review. Post notification?"
   - Show the formatted message from the prepare output
   - Options: "Post notification" / "Skip notification"
2. `effect == "auto-advance"` → Proceed directly to Step 3
   (post the notification) without prompting. Surface the
   returned `record` line in the transcript.
3. `effect == "skip"` → Skip notification entirely — go
   directly to Step 4 (checklist-only, no Slack, no reviewer
   assignment).
4. Response has an `error` key → fail safe: treat as `ask`.

**Unattended run (GH-1911):** the `ask` branch above, including an
`error` treated as `ask`, never fires its widget when this run is
unattended (the test Step 3a spells out). Nobody is there to answer
it, so a widget would stall the run. Treat it as `skip` instead: go
to Step 4 (checklist-only) and report
`Notification: skipped — external_notify asked in an unattended run`,
so the caller can request review once someone is watching.

### Step 3: Execute (if user approves)

If user approves, execute two delegated steps in sequence:

**Step 3a: Request review (GitHub + Slack)**

Pass the monitor's own mode through, as
[`references/review-readiness.md`](../../../references/review-readiness.md)
defines it: this run is **unattended** when it was invoked with
`--unattended`, or through `Skill()` while an orchestrator executes a
plan step with an active task list. Anything else is attended. Without
the flag, `dev10x:request-review` treats the call as attended and may
fire its readiness widget inside a run nobody is watching.

1. Unattended run: `Skill(skill="dev10x:request-review", args="--pr {pr_number} --repo {repo} --unattended")`
2. Otherwise (attended): `Skill(skill="dev10x:request-review", args="--pr {pr_number} --repo {repo}")`

When its output has a line containing `Readiness: stopped —` (the bare
Step 1.6 marker or the Step 4 summary bullet), nobody was asked to
review: skip Step 3b and report the reasons.

The dev10x:request-review skill will:
- Assign GitHub reviewers from project config
- Post Slack review notification from project config
- Each step may skip independently based on per-project config

**Step 3b: Update PR checklist**

**Primary (MCP tool):** Call `mcp__plugin_dev10x_cli__pr_notify`
with `pr_number={pr_number}`, `repo={repo}`, `action="send"`,
`skip_slack=true` and `skip_reviewers=true`.

**Fallback (script):** Only when the MCP server is unavailable:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  send --pr {pr_number} --repo {repo} \
  --skip-slack --skip-reviewers
```

This call runs checklist-only mode — no Slack posting, no reviewer
assignment (those were handled by the delegated skill above).

### Step 4: Execute (if user declines)

If user declines the notification, run checklist-only: the same
`pr_notify` call as Step 3b (`action="send"`, `skip_slack=true`,
`skip_reviewers=true`), or, only when the MCP server is unavailable:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  send --pr {pr_number} --repo {repo} \
  --skip-slack --skip-reviewers
```

### Step 5: Report final status

Run the status report command and include its output in the final report:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  status --pr {pr_number} --repo {repo}
```

This outputs a markdown report with three sections:
- **CI Check Status** — table with check name, pass/fail, duration
- **Review Comments** — count and list of unhandled comments
- **Reviewers** — table with reviewer names and review status

Include the full output in the agent's final report to the supervisor.

## Phase 3.5: Post-Merge Milestone Cleanup (GH-187)

If the PR has merged (state observed by `haiku-ci-poll` as
`MERGED`, or `gh pr view --json state,milestone` shows
`state: MERGED`) and the PR was assigned to a milestone,
check whether the milestone can now be closed.

1. Read `milestone.number` and `milestone.open_issues` from
   `gh pr view --json milestone`.
2. If `open_issues == 0`, call the MCP tool:
   ```
   mcp__plugin_dev10x_cli__milestone_close(number=<N>)
   ```
   This wraps `gh api -X PATCH repos/{repo}/milestones/{N} -f
   state=closed` — which the plugin's permission manifest blocks
   at the Bash layer. The MCP tool has the permission baked in.
3. If `open_issues > 0`, skip the close — the milestone still
   has work. Report `Milestone #{N}: {open_issues} open issues
   remaining` in the final status.

Skip this phase if `milestone == null`. Never invoke
`milestone_close` via raw `gh api` — the permission gap is
intentional outside the MCP tool.

## Phase 3.6: Post-Merge Link Reconciliation (GH-1274)

A merged PR's `Fixes:` trailer does not reliably close its issues
on a merge to `develop`. One merge closed two of three identical
trailers; a later session recorded **0 of 7** across two merges;
a third closed two of three again. Both spellings (full URL and
bare `#N`) failed in the 0-of-7 run, so the form is not the
variable. Nothing noticed any of it: the issue simply stayed open
and the bundle read as complete.

Run this whenever the PR is `MERGED`, milestone or not:

1. Read the merged PR's body — `mcp__plugin_dev10x_cli__pr_get(
   number=<N>)`.
2. Extract the closing links with
   `dev10x.skills.merge.fixes_scope.fixes_links(body)`.
3. For each linked number, read its real state with
   `mcp__plugin_dev10x_cli__issue_get(number=<n>)`.
4. Pass the numbers and states to
   `reconcile_link_closure(body=..., issue_states=...)` and
   report `summary()`.

Do **not** close a straggler silently. Report it — "GH-1268 was
linked but is still open" — and let the supervisor confirm the
scope actually shipped before closing it with `issue_close`. A
wrongly-closed issue reads as settled and drops out of every
future sweep.

An issue whose state could not be read is reported as **unread**,
never as closed. Counting an unread state as a closure would
recreate the silence this phase exists to break.
