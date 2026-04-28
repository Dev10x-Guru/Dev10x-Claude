# PR Review Monitor — Instructions

## Overview

This skill launches a **background agent** that autonomously monitors a PR
through its full lifecycle — CI checks, review comments, and team
notification. The user continues working while the agent handles everything.

**When to use this skill:**
- After creating a draft PR with `/Dev10x:gh-pr-create`
- When you want to automate the PR review cycle without blocking your session

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next.
Never pause to ask "should I continue?" between phases.

**REQUIRED: Create tasks after launch.** The background agent
executes these `TaskCreate` calls before any monitoring work:

1. `TaskCreate(subject="Detect PR context and launch agent", activeForm="Detecting PR context")`
2. `TaskCreate(subject="Check JTBD Job Story (Phase 0)", activeForm="Checking Job Story")`
3. `TaskCreate(subject="Monitor CI checks (Phase 1)", activeForm="Monitoring CI")`
4. `TaskCreate(subject="Address review comments (Phase 2)", activeForm="Addressing comments")`
5. `TaskCreate(subject="Assess QA scope (Phase 2.5)", activeForm="Assessing QA scope")`
6. `TaskCreate(subject="Notify re-review (Phase 2.7)", activeForm="Notifying re-review")`
7. `TaskCreate(subject="Send review notification (Phase 3)", activeForm="Sending notification")`
8. `TaskCreate(subject="Verify acceptance criteria (Phase 4)", activeForm="Verifying acceptance criteria")`

Set dependencies: each phase blocked by its predecessor. Phases
2.5 and 2.7 are conditional — skip via TaskUpdate status="deleted"
when their trigger conditions are not met.

**Background agents:** This skill already uses a background Task
agent. Task tracking wraps the agent phases so the supervisor
sees progress without reading the agent output file.

## Execution Model

```
User invokes /Dev10x:gh-pr-monitor
    │
    ├── 1. Detect PR number, repo, URL
    ├── 2. Launch background Task agent
    ├── 3. Tell user: "Monitoring in background, output at {path}"
    │
    └── User continues working
            │
            └── Background agent runs autonomously:
                ├── Phase 0: JTBD Job Story check (autonomous)
                ├── Phase 1: CI monitoring (autonomous)
                ├── Phase 2: Comment handling (autonomous)
                ├── Phase 2.5: QA scope assessment (asks user)
                ├── Phase 2.7: Re-review notification (asks user)
                ├── Phase 3: Notification (asks user first)
                └── Phase 4: Acceptance criteria verification (autonomous)
```

## Launch Instructions

When the user invokes `/Dev10x:gh-pr-monitor`:

### Step 1: Detect PR context

**Primary (MCP tool):** Call `mcp__plugin_Dev10x_cli__pr_detect`
with the PR argument (URL, bare number, or empty). Parse
`PR_NUMBER`, `REPO`, `PR_URL`, `BRANCH` from the response.

**MCP server unavailable.** If the tool is listed as "no longer
available" in system-reminders, STOP and ask the user to reconnect
via `/mcp` or a session restart. Do NOT fall back to the wrapper
script or use `DEV10X_SKIP_CMD_VALIDATION` — see
`references/mcp-unavailable-escape-hatch.md`.

**Fallback (script):** Only when the MCP server is healthy but the
tool call errored for another reason:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-context/scripts/gh-pr-detect.sh "$ARG"
# Parse PR_NUMBER, REPO, PR_URL, BRANCH from KEY=VALUE stdout
```

Pass `$ARG` as the skill argument (PR URL, bare number, or empty).
Both methods fetch `BRANCH` via `gh pr view --json headRefName`
— never from local git — which is critical in multi-worktree setups.

If the script exits non-zero, tell the user and stop.

### Step 2: Check for poll mode

Read the state file at `/tmp/Dev10x/pr-monitor/state-{pr_number}.json`
(if it exists). If the state file contains `phases_completed` that includes
**both** `phase0` and `phase3`, offer **lightweight polling** instead:

Use `AskUserQuestion`:
- **"Start polling (Recommended)"** — launches poll in a background shell
- **"Full agent"** — launches a full background agent as before

### Step 3: Launch background agent

Use the **Task tool** with these parameters:

```
subagent_type: "general-purpose"
model: "haiku"
mode: "dontAsk"
run_in_background: true
max_turns: 200
description: "Monitor PR #{pr_number}"
prompt: <see "Agent Prompt Template" below, with variables filled in>
```

**REQUIRED: `mode: "dontAsk"` on the Agent call.** Without
this, background agents lack Bash permissions to run CI
polling scripts and `gh` commands. They fall back to raw
alternatives which also hit permission friction, effectively
skipping the re-monitoring step (GH-695). The `dontAsk` mode
grants the agent permission to execute tools without prompts
— safe here because the agent only runs read-only CI checks
and `gh pr ready`.

**REQUIRED: `max_turns: 200` on the Agent call.** Without this,
haiku agents exhaust their default budget (~19 Bash calls) before
CI completes on long-running suites. Sessions GH-446 and GH-931
confirmed this failure mode — session `da0d9c73` saw the agent
exit after 18 tool calls with CI still pending. Always include
`max_turns: 200` in the Agent parameters — it is not optional.

**Anti-pattern (GH-931):** When the monitor agent exhausts its
budget, the parent orchestrator must NOT retry by dispatching a
raw `Agent()` call instead of re-invoking `Skill(Dev10x:gh-pr-
monitor)`. Raw Agent dispatch bypasses the skill's max_turns,
mode, and task tracking guarantees. If the monitor fails,
re-invoke the skill — not a raw agent.

**Why haiku?** Monitoring agents run `gh pr checks --watch` and
report pass/fail — they do not need Opus-level reasoning. Using
haiku reduces cost without affecting monitoring quality.

**Long CI suites (> 10 min):** Haiku agents may still exhaust
their budget on test suites that take 10+ minutes (GH-497 F5).
If the project's CI regularly exceeds 10 minutes, use
`model: "sonnet"` instead of `model: "haiku"` for the monitor
agent. The main session should also set `max_turns: 400` for
these projects.

### Step 4: Report to user

**DO NOT SKIP this step in any mode (full agent or poll).**

**REQUIRED: Create a caller-side tracking task (GH-854).**
After launching the background agent, create a visible task
in the calling session so the supervisor sees ongoing work:

```
TaskCreate(
    subject="PR #{pr_number} monitor running (background)",
    description="Background agent monitoring CI and review "
                "cycle. Output at {output_file}",
    activeForm="Monitoring PR #{pr_number}")
TaskUpdate(taskId=..., status="in_progress")
```

Mark this task `completed` ONLY when the background agent's
completion notification arrives. Do NOT mark it completed on
dispatch — the task must remain `in_progress` while the agent
runs. Without this task, the session appears idle and the
supervisor may close it prematurely.

Tell the user:
- PR monitor is running in the background
- Show the output file path from the Task result
- They can check progress anytime by reading that file
- The agent will ask for confirmation before posting notifications

---

## Agent Prompt Template

Fill in `{pr_number}`, `{repo}`, `{pr_url}`, `{branch}` and pass as
the prompt:

````
You are a PR monitoring agent running in the background.

**Target:** PR #{pr_number} in {repo}
**URL:** {pr_url}
**Branch:** {branch}

Your job: autonomously shepherd this PR from draft → CI passing →
comments addressed → review requested. Execute the early-exit check
first, then Phase 0, 1, 2, 2.5, and 3 in order.

---

## Early-Exit Check

Before running any phases, check if work has already been done by
reading the state file and comparing against current PR state.

1. Read `/tmp/Dev10x/pr-monitor/state-{pr_number}.json` (if exists)
2. Fetch current PR state:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/ci-check-status.py \
     --pr {pr_number} --repo {repo}
   gh pr view {pr_number} --repo {repo} --json state,reviews,comments
   ```
3. Compare against saved state
4. If ALL match and no new data → exit with:
   "No changes since {last_checked}. Nothing to do."
5. If changed → run only the relevant phases
6. Skip phases listed in `phases_completed` from the state file

---

## Phase 0: JTBD Job Story Check

The PR body **must** start with a JTBD Job Story as its first paragraph.

1. Fetch the current PR body:
   ```bash
   gh pr view {pr_number} --json body -q '.body'
   ```

2. Check if the first paragraph matches the Job Story pattern:
   - Starts with `**When**` (bold "When")
   - Contains `**I want to**` and `**so I can**`

3. If a valid Job Story is present → skip to Phase 1.

4. If missing or malformed → generate one using the `Dev10x:ticket-jtbd` skill.

5. After the skill completes, verify the PR body now starts with the
   Job Story.

---

## Phase 1: CI Monitoring Loop

Repeat until all CI checks pass:

1. Check CI and merge conflict status using the structured verdict script
   (the script checks both CI checks and PR mergeable status):
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/ci-check-status.py \
     --pr {pr_number} --repo {repo}
   ```
   The script returns JSON with a `verdict` field:
   ```json
   {"verdict": "green|pending|failing|conflicting|empty",
    "mergeable": "MERGEABLE|CONFLICTING|UNKNOWN",
    "total": 5, "pass": 3, "fail": 0, "pending": 2, ...}
   ```

2. Act on the `verdict` field — **nothing else**:
   - `"green"` → **re-check for review comments before marking
     ready** (see Post-CI Comment Re-check below), then Phase 2
   - `"conflicting"` → PR has merge conflicts. Rebase onto base
     branch and force-push (see Conflict Handling below). The
     script checks `mergeable` status from the GitHub API — this
     verdict takes priority over CI check results (GH-563).
   - `"pending"` → wait 30 seconds via `sleep 30`, re-run the
     script. **Hard rule: Do NOT exit Phase 1 while verdict is
     "pending".** The loop MUST continue until verdict changes
     to `"green"` or `"failing"`. Exiting early with pending
     checks was the #1 monitor regression (GH-447 F1, GH-553).
   - `"failing"` → read the `checks` array to identify which
     checks failed, then fix (see CI Failure Handling below)
   - `"empty"` → GitHub hasn't registered check suites yet.
     Wait 60 seconds and re-run. This is expected immediately
     after a push or after converting a draft PR to ready.

   **Draft-to-ready SKIPPED guard (GH-774):** When a draft PR
   is converted to ready via `gh pr ready`, GitHub marks
   existing check runs as SKIPPED before new suites start.
   The script returns `"empty"` when all checks are SKIPPED
   (non_skipping == 0). This is NOT CI-green — it means
   GitHub has not registered new check suites yet. The agent
   MUST loop until at least one non-skipping check appears.
   A monitor completing in under 60 seconds on a freshly-
   readied PR is suspect — SKIPPED checks are not terminal.

   **Do NOT parse `gh pr checks` text output directly.**
   Always use the script — it handles bucket classification,
   SKIPPING exclusion, and check counting reliably (GH-553).

3. After fixing CI failures or pushing new commits, wait **60
   seconds** before the first re-check. GitHub needs time to
   register new check suites after a push — checking too early
   returns stale results from the previous commit.

4. **Check count is handled by the script.** The `total` and
   `pass` fields in the verdict JSON include the count. If
   `verdict` is `"empty"` after a push, wait and retry — the
   script already excludes SKIPPING checks from the pass count.

### CI Failure Handling

| Failure Type | How to Fix |
|---|---|
| ruff/black/isort | Auto-format; commit and push |
| mypy | Add/fix type annotations |
| flake8 | Remove unused imports, fix style issues |
| gitlint (title > 72 chars) | Amend commit message |
| pytest failures | Read test, fix code or update expectations |
| Import errors | Update import paths |
| Coverage < 100% | Add tests for uncovered lines |
| git-history-linting (fixup! commits) | Auto-groom: `git autosquash-{base}` then `git push --force-with-lease`. Wait 60s, resume Phase 1 loop. See `ci-failure-patterns.md` for detection and full procedure. |

For each CI fix:
- Implement the fix
- Stage changes: `git add {files}`
- Create fixup commit targeting the appropriate original commit
- Push: `mcp__plugin_Dev10x_cli__push_safe(args=["origin", "HEAD"])`

### Conflict Handling

When `gh pr view` reports `mergeable: CONFLICTING`:

1. Resolve the base branch via `mcp__plugin_Dev10x_cli__pr_detect`
   (returns `baseRefName`).

2. Delegate the rebase + force-push to `Skill(Dev10x:git-groom)` —
   it fetches the base, rebases, and runs the protected-branch
   safety checks before force-pushing. Do NOT call `git rebase` or
   `git push --force-with-lease` directly from this skill: routing
   through the wrapper preserves the autosquash, gitmoji, and
   protected-branch guardrails (see Skill Routing Enforcement in
   `skills/work-on/instructions.md`).

3. If `Dev10x:git-groom` reports unresolved conflicts, stop the
   monitor and report the conflicting files to the user.

4. After the wrapper completes the force-push, wait 30 seconds for
   GitHub to re-compute mergeability and re-run CI, then restart the
   Phase 1 loop.

### Post-CI Comment Re-check (REQUIRED)

**Hard rule (GH-465):** After ALL CI checks pass, re-check for
review comments BEFORE marking the PR ready. CI hygiene reviews
(automated code review workflows) post comments *during* the CI
run — they arrive after the initial comment check at Phase 1
startup. Without this re-check, the PR gets marked ready with
unaddressed comments.

1. Fetch unresolved review threads (use the GraphQL query from
   Phase 2's "Counting Unaddressed Comments" section)
2. Fetch all reviews and check for **unaddressed body-only
   findings** (GH-564). For each review, if the body contains
   structured findings (severity markers like `CRITICAL:`,
   `BLOCKING:`, `INFO:`, numbered items with file:line refs,
   or bold-prefixed items like `**[BLOCKING]**`) that have not
   been replied to with a top-level PR comment, count them as
   unaddressed. Query reviews via:
   ```bash
   gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews \
     --jq '[.[] | select(.body != "" and .body != null)
     | {id, user: .user.login, body, state}]'
   ```
   Then check if each review body's findings have corresponding
   top-level PR comment replies (matching `Re:` prefix pattern).
3. Fetch top-level PR comments (GH-698) and check for
   unaddressed automated review findings:
   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/check-top-level-comments.sh \
     {owner} {repo} {pr_number}
   ```
   Returns a JSON array of unaddressed findings (empty = pass).
   Top-level comments are invisible to the `reviewThreads`
   GraphQL query — they use a separate API surface
   (`issueComments`). Without this check, automated review
   findings posted as top-level comments are silently skipped.
4. If unresolved threads OR unaddressed body findings OR
   unaddressed top-level comments exist → enter Phase 2 to
   address them. Do NOT mark PR ready yet.
5. If no unresolved threads AND no unaddressed body findings
   AND no unaddressed top-level comments → mark PR ready
   (`gh pr ready {pr_number}`) and proceed to Phase 2 for
   a final check.

This re-check prevents the race condition where automated
reviewers post during CI, and ensures body-only review
findings and top-level automated comments are not silently
skipped.

---

## Phase 2: Review Comment Monitoring Loop

Repeat until no unaddressed comments remain:

1. Delegate to `Dev10x:gh-pr-respond` in **batch mode** with the PR URL:
   ```
   Skill(skill="Dev10x:gh-pr-respond", args="{pr_url}")
   ```

2. After all comments are addressed, return to Phase 1 (CI may re-run
   after pushes).

3. When Phase 1 passes AND no unaddressed comments remain → go to
   Phase 2.5.

### Counting Unaddressed Comments (Thread Resolution Awareness)

**CRITICAL (GH-464):** Do NOT count root PR comments as unaddressed
based solely on the REST API (`gh api .../pulls/.../comments`). The
REST API returns ALL root comments regardless of thread resolution
status. Use the GraphQL `reviewThreads` query to check `isResolved`:

```bash
gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 1) {
            nodes { databaseId path body author { login } }
          }
        }
      }
    }
  }
}' -f owner='{owner}' -f repo='{repo}' -F pr={pr_number} \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.isResolved == false)
        | .comments.nodes[0]]'
```

Only threads where `isResolved == false` AND the author has not
replied count as unaddressed. Resolved threads are done — do not
report them as needing attention.

### Exit condition for Phase 2 loop

Move to Phase 2.5 when ALL of these are true:
- All CI checks passing
- No unresolved review threads (use GraphQL `isResolved` check)
- No unaddressed body-only review findings (GH-564) — check
  review bodies for structured findings without corresponding
  top-level PR comment replies
- No unaddressed top-level automated review comments (GH-698)
  — check `issueComments` for severity markers from bot users
- PR has at least one approval OR no reviews yet

---

## Phase 2.5: QA Scope Assessment (REQUIRES USER CONFIRMATION)

This phase runs ONCE when Phase 2 completes. It delegates to the
`Dev10x:qa-scope` skill if available.

1. Invoke the Dev10x:qa-scope skill:
   ```
   Skill(skill="Dev10x:qa-scope", args="{pr_number}")
   ```

   The Dev10x:qa-scope skill will:
   - Analyze the PR diff for QA risk (low/medium/high)
   - Check the project's e2e test directory for existing coverage
   - Present a QA assessment to the user via AskUserQuestion

2. Wait for the skill to complete before proceeding to Phase 3.

3. If Dev10x:qa-scope determines the change is low-risk (config-only,
   test-only, docs-only), it will skip ticket creation automatically.

**Note:** This phase only runs once per PR monitor session. If already
executed, skip directly to Phase 3.

---

## Phase 2.7: Re-review Notification (REQUIRES USER CONFIRMATION)

This phase runs when Phase 2 addressed review comments (i.e., at least
one reviewer requested changes and those changes have been pushed). Skip
if Phase 2 found no comments to address.

**Trigger:** PR had CHANGES_REQUESTED reviews AND fixup commits were
created to address them.

### Step 1: Identify reviewers who requested changes

```bash
gh pr view {pr_number} --json reviews \
  --jq '.reviews[] | select(.state=="CHANGES_REQUESTED") | .author.login'
```

### Step 2: Compose and format each notification

For each reviewer who requested changes, compose:
```
@{reviewer} please take another look
```

Format this as a Slack message suitable for posting.

### Step 3: Ask user for confirmation

Use `AskUserQuestion` showing the exact message that will be posted.

Options: "Post re-review notification" / "Skip".

### Step 4: Post the notification

If user approves, invoke the skill with the composed message. The skill
reads the project's Slack config and posts to the configured channel.

Example invocation:
```
Skill(skill="Dev10x:slack-review-request", args="--pr {pr_number} --repo {repo} --message '@{reviewer} please take another look'")
```

The Dev10x:slack-review-request skill will:
- Resolve the project's configured channel from userspace config
- Post the message to that channel
- Report the result back to the agent

---

## Phase 3: Notification (REQUIRES USER CONFIRMATION)

**CRITICAL: Do NOT post notifications without user confirmation.**

**Background agent auto-advance (GH-851 F1):** When dispatched
as a background agent with `mode: dontAsk`, auto-advance through
Phase 3 without stopping for confirmation. The `dontAsk` mode
from the parent implies blanket authorization for shipping
pipeline steps. Skip Step 2 (AskUserQuestion) and proceed
directly to Step 3 (execute notification).

### Step 0: Verify PR state via MCP

**Hard rule: Verify final PR state with the MCP tool — NEVER use
raw `gh pr view` or `gh pr checks`.**

`mcp__plugin_Dev10x_cli__verify_pr_state(pr_number={pr_number})`

Parse `is_draft`, `state`, `review_decision`, and `checks_passing`
from the response. Only proceed to notification if checks pass and
no blocking issues.

### Step 1: Prepare

Gather PR info, count open threads, verify readiness:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  prepare --pr {pr_number} --repo {repo}
```

If `open_threads > 0`, verify the count using GraphQL `isResolved`
(see "Counting Unaddressed Comments" in Phase 2). Only return to
Phase 2 if unresolved threads actually exist — `pr-notify.py` may
count resolved threads as open if it uses the REST API.

*Why?* Reviewers should only be pinged when the PR is fully ready.

### Step 2: Ask user for confirmation

Use `AskUserQuestion`:
- Question: "PR #{pr_number} is ready for review. Post notification?"
- Show the formatted message from the prepare output
- Options: "Post notification" / "Skip notification"

### Step 3: Execute (if user approves)

If user approves, execute two delegated steps in sequence:

**Step 3a: Request review (GitHub + Slack)**

```
Skill(skill="Dev10x:request-review", args="--pr {pr_number} --repo {repo}")
```

The Dev10x:request-review skill will:
- Assign GitHub reviewers from project config
- Post Slack review notification from project config
- Each step may skip independently based on per-project config

**Step 3b: Update PR checklist**

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-monitor/scripts/pr-notify.py \
  send --pr {pr_number} --repo {repo} \
  --skip-slack --skip-reviewers
```

This call runs checklist-only mode — no Slack posting, no reviewer
assignment (those were handled by the delegated skill above).

### Step 4: Execute (if user declines)

If user declines the notification, run checklist-only:

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

---

## Phase 4: Acceptance Criteria Verification

After Phase 3 completes, verify acceptance criteria before the
agent's final status report. This catches uncommitted files,
failing checks, or incomplete work that earlier phases missed.

1. Invoke the verification skill:
   ```
   Skill(skill="Dev10x:verify-acc-dod")
   ```

   The skill auto-detects the work type from session context and
   adapts to the current friction level. At `adaptive` level it
   runs fully unattended — auto-passing or auto-failing without
   blocking the agent.

2. If all checks pass → include "Acceptance criteria: PASSED" in
   the final status report.

3. If any check fails → include "Acceptance criteria: FAILED" with
   the failing checks in the final status report. Do NOT re-enter
   earlier phases — report the failures and let the supervisor
   decide next steps.

**Permission failure propagation (GH-760 F4):** If the
background agent hits permission limits and cannot complete
`verify-acc-dod`, it MUST report this explicitly as
"Acceptance criteria: INCOMPLETE — permission failure" in the
final status report. The parent orchestrator MUST re-invoke
`Skill(Dev10x:verify-acc-dod)` in the main session when it
sees this status. Do NOT mark the parent's acceptance task
as `completed` when the agent reports incomplete.

### Main-Session Fallback (GH-901)

**Hard rule:** When a background agent launched with
`mode: dontAsk` still lacks Bash permissions or fails to
complete any phase due to permission friction, the parent
orchestrator MUST immediately re-run the failed phase in
the main session. Do NOT treat a permission-failed background
agent as a successful completion.

**Detection:** The background agent's completion notification
includes its final status. Check for:
- Explicit "permission failure" or "INCOMPLETE" in the result
- Agent completing in under 60 seconds (suspect — likely
  skipped phases due to permission denials)
- Missing phase completion markers in the result summary

**Fallback protocol:**
1. Log: "Background agent failed — re-running in main session"
2. Re-invoke the monitoring skill directly (not as a background
   agent) so it inherits the main session's permissions
3. Mark the background agent's tracking task as `completed`
   with description "Failed — re-ran in main session"
4. The main-session re-run replaces the background agent's
   results entirely

````

---

## Important Rules

- **Monitoring scope**: This skill monitors CI checks and review
  comments up through review request (Phase 3), then verifies
  acceptance criteria (Phase 4). It does NOT monitor through to
  merge. After Phase 4 completes, the agent exits. To monitor
  post-approval activity or wait for merge, re-invoke the skill
  or check manually.
- **Do NOT merge PRs.** The monitoring agent must never run
  `gh pr merge`, `git merge`, or any merge operation. Merging
  is the supervisor's responsibility. If the agent merges
  autonomously, the main session may attempt a duplicate merge
  and hit "already merged" errors.
- **Autonomous execution**: Phase 1 and Phase 2 run without asking the
  user. Phase 2.5 (QA) and Phase 3 (notification) need confirmation.
- **One fixup per comment**: Each review comment gets exactly one fixup
  commit.
- **Poll interval**: Wait 30 seconds between CI checks and comment checks.
- **Max CI retries**: If CI fails 5 times in a row on the same issue,
  stop and report the problem.
- **No regular force push**: Use `mcp__plugin_Dev10x_cli__push_safe` for normal pushes.
  Exception: after conflict rebase, use `git push --force-with-lease`.
- **Working directory**: Use `gh pr view {pr_number} --repo {repo}
  --json headRefName` to get the branch. Never hardcode a working
  directory — the PR branch may live in a different worktree.
- **Background agent permissions**: Background agents are launched
  with `mode: "dontAsk"` (GH-695) to avoid permission friction
  on CI polling scripts and `gh` commands. This is safe because
  the agent only runs read-only operations (CI checks, PR status)
  and `gh pr ready`. If the agent needs to push fixes (CI failure
  handling), it uses `mcp__plugin_Dev10x_cli__push_safe` which
  is already permitted via MCP.

---

## Integration with Other Skills

1. **Dev10x:gh-pr-create** — Use before this skill to create the draft PR
2. **Dev10x:ticket-jtbd** — Delegated to by the agent in Phase 0
3. **Dev10x:gh-pr-respond** — Delegated to by the agent for review comments (Phase 2)
4. **Dev10x:qa-scope** — Delegated to by the agent for QA risk assessment (Phase 2.5)
5. **Dev10x:request-review** — Delegated to by the agent in Phase 3 (combined GitHub + Slack review request)
6. **Dev10x:slack-review-request** — Delegated to by the agent in Phase 2.7 (re-review notification)
7. **Dev10x:verify-acc-dod** — Delegated to by the agent in Phase 4 (acceptance criteria)
8. **pr-notify.py** — Phase 3 helper script (checklist update only)

## Delegation Pattern

```
/Dev10x:gh-pr-monitor (this skill — launches background agent)
    │
    └── Background Task Agent
        │
        ├── Phase 0: JTBD Job Story check
        │       ├── Fetch PR body, check first paragraph
        │       └── If missing → Skill(skill="Dev10x:ticket-jtbd") to generate
        │
        ├── Phase 1: CI monitoring (handled directly by agent)
        │
        ├── Phase 2: Comment monitoring
        │       └── Skill(skill="Dev10x:gh-pr-respond", args="{pr_url}") — batch mode
        │
        ├── Phase 2.5: QA scope assessment
        │       └── Skill(skill="Dev10x:qa-scope")
        │
        ├── Phase 2.7: Re-review notification (after comments addressed)
        │       ├── AskUserQuestion → confirm notification
        │       └── Skill(skill="Dev10x:slack-review-request") → post to Slack
        │
        ├── Phase 3: Notification (initial review request)
        │       ├── AskUserQuestion → confirm message
        │       └── If approved, execute two delegated steps:
        │           ├── Skill(skill="Dev10x:request-review") → assign GitHub reviewers + post Slack
        │           └── pr-notify.py send (checklist-only mode)
        │
        └── Phase 4: Acceptance criteria verification
                └── Skill(skill="Dev10x:verify-acc-dod") → auto-pass/fail at adaptive level
```
