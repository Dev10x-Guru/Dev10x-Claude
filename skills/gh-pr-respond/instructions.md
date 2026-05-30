# Respond to PR Review Comments (Instructions)

**This skill is the recommended entry point for all PR review
comments.** It orchestrates the full pipeline: collect comments,
triage each one, implement fixes, reply, and resolve threads.
Do not call `Dev10x:gh-pr-fixup` or `Dev10x:gh-pr-triage`
directly unless you are handling the full pipeline yourself.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next — no checkpoints under adaptive friction.
Never pause to ask "should I continue?" between steps.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup based on the detected mode:

**Mode A (single):**
1. `TaskCreate(subject="Process comment r{id}", activeForm="Processing comment")`
2. `TaskCreate(subject="Hide obsolete comment", activeForm="Hiding comment")`
3. `TaskCreate(subject="Check remaining comments", activeForm="Checking remaining")`

**Mode B (batch):**
1. `TaskCreate(subject="Collect unaddressed comments", activeForm="Collecting comments")`
2. `TaskCreate(subject=f"Triage {N} comments", activeForm="Triaging comments")`
3. `TaskCreate(subject="Get user approval", activeForm="Awaiting approval")`
4. `TaskCreate(subject="Execute approved responses", activeForm="Executing responses")`
5. `TaskCreate(subject="Resolve threads", activeForm="Resolving threads")`
6. `TaskCreate(subject="Hide obsolete comments", activeForm="Hiding comments")`
7. `TaskCreate(subject="Summary", activeForm="Summarizing")`

Set dependencies and update status as each completes.

**Nested-mode exemption:** When invoked as a nested skill within
a parent orchestrator (e.g., via `Skill()` from `Dev10x:work-on`),
startup task creation is optional — at most 1 summary task. See
`references/task-orchestration.md` § Delegated Invocation Exception.

**Parallel triage (Mode B Step 2):** Dispatch up to 4 triage
subagents concurrently to reduce processing time. Each subagent
receives only its comment context and returns verdict + draft
reply.

**Batched decisions:** Thread resolution decisions are queued
and presented as a batch after all responses are posted.

## Playbook

This skill is playbook-powered. The workflow steps are defined in
`references/playbook.yaml` with two plays: `single` (Mode A) and
`batch` (Mode B).

**Loading order** (see `references/config-resolution.md`):
1. `.claude/Dev10x/playbooks/gh-pr-respond.yaml` (project-local)
2. `~/.claude/memory/Dev10x/playbooks/gh-pr-respond.yaml` (global + repo match)
3. `${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-respond/references/playbook.yaml`

Customize with `/Dev10x:playbook edit gh-pr-respond <play>`.

## Decision Gates

This skill has 7 **blocking decision gates** where execution
MUST pause for user input via the `AskUserQuestion` tool.

**Plain text questions are NOT acceptable** — they don't block
execution, don't provide clickable options, and break the
structured decision flow the user relies on.

Gates numbered by insertion order; execution order differs by mode.

| # | Location | Purpose |
|---|----------|---------|
| 1 | Mode A, Step 1b | Confirm thread resolution |
| 2 | Mode A, Step 3 | Continue / batch / stop |
| 3 | Mode B, Step 3 | Approve / review / skip batch |
| 4 | Mode B, Step 5 | Resolve threads confirmation |
| 5 | Post-Response Continuation | Groom + push + monitor / Push only / Stop |
| 6 | Mode B, Step 5b / Mode A, Step 1c | Hide obsolete comments |
| 7 | Mode A, Step 1d / Mode B, Step 4 (per bundle) | YAGNI routing — remove / defer / keep-and-harden |

Each gate is marked with **REQUIRED: `AskUserQuestion`** in the
step description. If you see that marker, you MUST call the
`AskUserQuestion` tool — never substitute with inline text.

**Compaction-safe gate checklist** — re-inject after compaction:

1. Gate 1 (thread resolution): `AskUserQuestion` — MANDATORY
2. Gate 2 (continue/batch/stop): `AskUserQuestion` — MANDATORY
3. Gate 3 (approve batch): `AskUserQuestion` — MANDATORY
4. Gate 4 (resolve threads): `AskUserQuestion` — MANDATORY
5. Gate 5 (shipping pipeline): `AskUserQuestion` — MANDATORY
6. Gate 6 (hide comments): `AskUserQuestion` — MANDATORY
   (fires at every friction level, including `adaptive`; adaptive
   auto-selects "Hide all resolved" but the gate still fires and
   `minimize_comments` is invoked — GH-208)
6a. Gate 7 (YAGNI routing): `AskUserQuestion` — MANDATORY per
    YAGNI bundle (GH-297). Adaptive auto-selects "Remove
    out-of-scope code" but the gate still fires so the user sees
    the bundled comment IDs before the removal commit is created.
7. VALID comments: `Skill(Dev10x:gh-pr-fixup)` — NEVER inline,
   invoke immediately after triage verdict (no pause, no report)
8. Triage: `Skill(Dev10x:gh-pr-triage)` — NEVER inline, even
   for "obviously invalid" or bot-generated comments (GH-463)
9. Pre-action checkpoint: BEFORE any `Edit` or `git commit` on
   a reviewed file, verify a `Skill()` call preceded it
10. Merge: `Skill(Dev10x:gh-pr-merge)` — NEVER inline
    `gh pr merge` (GH-759 F3)

## Overview

This skill handles PR review comments end-to-end in two modes:

1. **Single comment mode** — Given a specific comment URL, process that one
   comment, then check for remaining unaddressed comments and offer to continue.
2. **Batch mode** — Given a PR URL or review URL, collect all unaddressed
   comments, triage them, and present a response plan for user approval.

Sub-skills:
- **`Dev10x:gh-pr-triage`** — Validate the comment against the codebase
- **`Dev10x:gh-pr-fixup`** — Implement the fix if the comment is valid

```
Dev10x:gh-pr-respond (this skill)
    ├── Dev10x:gh-pr-triage         → validate, reply if invalid (never auto-resolves)
    ├── resolve gate      → ask user to confirm thread resolution
    └── Dev10x:gh-pr-fixup  → implement fix, fixup commit, reply with ref
         └── Dev10x:git-fixup → create the fixup! commit
```

## Critical: Delegation is Mandatory

**Never manually implement a fix and post a reply via `gh api`
or MCP tool for VALID comments.** Always delegate the entire
lifecycle to `Dev10x:gh-pr-fixup` via `Skill()`, even if the
fix is trivial or already committed. The delegation is about
the *workflow boundary*, not just the code change — `gh-pr-fixup`
ensures atomic push+reply, proper fixup commit format, and
consistent thread management.

Similarly, never triage comments inline — always delegate to
`Dev10x:gh-pr-triage` via `Skill()`. Never run raw `git rebase`,
`git push`, or `gh pr checks --watch` — delegate to
`Dev10x:git-groom`, `Dev10x:git`, and `Dev10x:gh-pr-monitor`
respectively.

**Post-step self-check:** Before marking any VALID comment as
processed, verify that `Skill(Dev10x:gh-pr-fixup)` was called
for it — not `Edit` + `git commit` + `gh api`. If you used
raw commands instead of `Skill()`, STOP and redo the step with
proper delegation. Audit sessions show 3 of 4 invocations
bypass delegation under context pressure (GH-444).

**Pre-action intervention checkpoint:** If you are about to call
`Edit` on a file mentioned in a review comment, or about to run
`git commit`, STOP and ask yourself: "Did I invoke `Skill()`
for this?" If the answer is no, you are bypassing delegation.
The correct sequence is ALWAYS:
1. `Skill(Dev10x:gh-pr-triage)` → verdict
2. If VALID: `Skill(Dev10x:gh-pr-fixup)` → fix + commit + reply
3. Never: `Edit` → `git commit` → `gh api` (this is the bypass)

**Anti-pattern: "Stated-but-not-executed" bypass (GH-458).**
The most common bypass is acknowledging the delegation requirement
in your reasoning ("I need to call Skill(Dev10x:gh-pr-fixup)")
then proceeding to implement the fix inline anyway. Three audit
sessions caught this exact pattern — the agent says it will
delegate, then does the work itself. Stating intent is not
execution. Only a `Skill()` tool call counts as delegation.

**Pre-push TaskList self-check (GH-97):** Before any `git push`
or `Skill(Dev10x:git)` invocation that ships fixup commits,
call `TaskList` and verify that every comment marked
"completed" with verdict VALID has an associated
`Skill(Dev10x:gh-pr-fixup)` call recorded in the task
metadata or a sibling subtask. If a VALID comment is marked
completed but no `Skill()` invocation is recorded for it, STOP
and re-run that comment through `Skill(Dev10x:gh-pr-fixup)`.
This guardrail exists because at `adaptive` friction, three
audit sessions in a row bypassed the delegation under context
pressure (~42% compliance). The REQUIRED markers above are
necessary but not sufficient — the TaskList evidence check is
the trailing audit that catches the bypass before it ships.

## Bundled Fixup Mode (GH-86, GH-97)

Default behavior is one `fixup!` commit per comment. The bundled
mode is the explicit carve-out for refactors that naturally
address several review threads at once — e.g., a single rename
that closes three comments, or a helper extraction that closes
two threads on the same file region.

### Trigger criteria

Enter bundled mode when ALL of the following are true:

1. Two or more VALID comments target the same file/region or
   share the same underlying issue.
2. The fix is a single coherent change — splitting it into one
   fixup per comment would produce duplicate diffs or
   semantically identical commits.
3. The user has not explicitly asked for separate fixups.

When in doubt, default to one fixup per comment. Bundling is
opt-in for the agent: offer it via `AskUserQuestion` rather
than auto-bundling silently.

### Rationalization Watchlist (GH-123)

**Reject bundled mode** when the agent's stated rationale matches
any of the patterns below. These are well-formed but invalid
rationalizations that audit session GH-123 caught a 9-comment
review cycle silently bundling under. The trigger criteria above
require shared *fix scope*, not shared *commit topology* or
*implementation efficiency*.

Prohibited rationalizations:

- "Both comments touch the same parent commit"
- "Autosquash will collapse them anyway"
- "Fewer stash / checkout / rebase dances"
- "About the same area of code" (without single-fix coherence)
- "These are all in the same file"
- "Easier to land one fixup than three"

These patterns describe convenience or commit topology — neither
satisfies the "single coherent change" criterion. If the rationale
for bundling fits any pattern above, STOP and produce one fixup
per comment. The trigger criteria are about the *fix*, not the
*workflow*; if splitting produces three distinct diffs, those
distinct diffs need three distinct fixups.

### Pre-fixup comment-ID checkpoint (GH-123)

Before invoking `Skill(Dev10x:gh-pr-fixup)`, record which review
comment ID(s) the fixup addresses in the task metadata for that
step:

```
TaskUpdate(taskId, metadata={"comment_ids": ["<id1>"], "bundled": false})
```

For bundled fixups, the metadata MUST list every grouped comment
ID and the bundle rationale:

```
TaskUpdate(taskId, metadata={
    "comment_ids": ["<id1>", "<id2>", "<id3>"],
    "bundled": true,
    "bundle_rationale": "<one-sentence shared-fix-scope reason>",
})
```

The `bundle_rationale` field is the audit trail. If the rationale
matches the Rationalization Watchlist above, the task MUST be
rejected and split into separate fixups before invoking
`Skill(Dev10x:gh-pr-fixup)`. This makes the "memory-only" rule a
mechanical guardrail: the metadata records the decision, the
watchlist filters bad rationales, and `Dev10x:skill-audit` can
surface patterns of bundling decisions across sessions.

### Bundled-reply template

When a single `fixup!` addresses N comments, every reply MUST
include the same template, hyperlinked. Plain-text SHA tails
(e.g., `` (fixup `<sha>`) ``) are PROHIBITED — they become
orphan references the moment `Dev10x:git-groom` rewrites
history.

```markdown
{contextual response to the reviewer's point}

**Fix commit:** [`<short-sha>`](https://github.com/{repo}/pull/{pr}/commits/<sha>)
**Code change:** [`<file>:<lines>`](https://github.com/{repo}/blob/<branch-head-sha>/<path>#L<start>-L<end>)

Note: this fix is bundled with {N-1} other thread(s) into a single
`fixup!` commit and will be squashed into its parent during
`Dev10x:git-groom`.
```

Rules:

- The `Fix commit:` URL uses the `/pull/{N}/commits/<sha>` form,
  which GitHub resolves in the PR commits tab even after force
  push (the bare `/commit/<sha>` form does not).
- The blob URL pins to the **current branch HEAD SHA**, not the
  fixup SHA. The fixup SHA disappears at squash time; the
  branch-head SHA stays valid until the next force push (and
  the post-groom refresh step below re-pins it then).
- Every bundled reply explicitly states it is bundled. Reviewers
  must be able to tell from any single thread that the same fix
  resolves siblings.
- Track the comment IDs grouped under each fixup in skill state
  so the post-groom refresh phase can locate them.

### Post-Groom SHA Refresh (sub-phase of shipping pipeline)

After `Skill(Dev10x:git-groom)` rewrites history (fixups
squashed, force push complete), any reply posted earlier in
this session that references a pre-groom SHA is now stale.
Refresh those replies before the merge gate.

Sequence (runs between groom and push-monitor steps):

1. Collect every reply this skill posted in the current session
   that referenced a `fixup!` SHA or its pre-rebase parent. The
   bundled-mode grouping (above) is the authoritative source.
2. For each tracked reply:
   a. Resolve the new parent SHA (the squashed-into commit).
   b. Rewrite the reply body using the bundled-reply template,
      substituting the new parent SHA for `Fix commit:` and the
      new branch-head SHA for the blob URL.
   c. PATCH the reply via
      `mcp__plugin_Dev10x_cli__pr_comments(action="edit", ...)`.
      Never drop to raw `gh api -X PATCH` — the `edit` action
      exists precisely so the post-groom refresh stays inside
      the structured tool surface.
3. Mark the refresh task complete only after every tracked
   reply was successfully PATCHed. A 404 (comment deleted by
   reviewer) is acceptable; any other failure must abort the
   refresh and surface the error.

Skip this sub-phase when no replies were posted in the current
session (e.g., resumed from a different process) OR when no
fixup commits exist on the branch.

## Preamble: Branch Location Check

Before processing comments, verify the PR branch is accessible
from the current working directory. In multi-worktree setups, the
PR branch may live in a different worktree than the active CWD.

**Step 0: Ensure worktree tool availability.**
Call `ToolSearch("select:EnterWorktree")` before any worktree
detection. If unavailable, warn and stop — do NOT silently fall
back to `git -C` (GH-759 F1). The `git -C` fallback cascades
across nested skills, breaking allow-rule matching.

1. Extract the PR branch name via
   `mcp__plugin_Dev10x_cli__pr_detect(arg="<pr_number>")` —
   returns `head_ref` (the branch name) along with `repo` and
   `state`. No raw `gh pr view` call is needed.
2. Check if the branch is checked out in the current worktree:
   ```bash
   git symbolic-ref --short HEAD
   ```
3. If the current branch does NOT match the PR branch:
   - Check `git worktree list` for the PR branch
   - If found in another worktree, use `EnterWorktree` to
     switch context. Do NOT use `git -C` as a workaround.
   - If not found anywhere, check it out:
     `git checkout {branch}`

This prevents wasted turns from file-not-found errors when
the agent reads files that exist only on the PR branch.

## Preamble: Spec Drift Check (GH-173)

Before responding to review comments, check whether the PR's
changes have drifted from the canonical spec at
`docs/specs/<TICKET-ID>.md`. If the ticket has no canonical
spec, **no-op** — this guard only fires when SPDD-style scoping
is in use.

```python
from pathlib import Path
from dev10x.spec import detect_drift, DriftKind

ticket_id = "<extracted from PR branch>"
spec_path = Path(f"docs/specs/{ticket_id}.md")
if spec_path.exists():
    report = detect_drift(
        spec_path=spec_path,
        project_root=Path("."),
    )
    if report.has_behavioural:
        # SURFACE AS BLOCKER — do not auto-fix.
        ...
    elif report.has_structural:
        # SURFACE AS WARNING with Dev10x:spec-sync suggestion.
        ...
```

**Behavioural drift is a blocker.** Surface to the user:

> "Spec drift detected: behavioural drift in
> `docs/specs/<TICKET-ID>.md`. Per the Golden Rule, fix the
> prompt first. Invoke `Dev10x:spec-update` before responding
> to review comments — otherwise fixup commits will compound
> the drift."

Stop the skill. Do not proceed to Mode A or Mode B until the
user has either resolved the drift or explicitly opted to
override (rare — used only when the reviewer's comment IS the
spec update).

**Structural drift is a warning.** Surface to the user, but
allow the response flow to continue:

> "Spec drift detected: structural drift in
> `docs/specs/<TICKET-ID>.md`. The Architecture / Implementation
> Steps sections lag the current code shape. Consider running
> `Dev10x:spec-sync` after this PR merges."

**No spec means no-op.** If `docs/specs/<TICKET-ID>.md` does
not exist, skip this preamble silently and continue to Input
Detection. Projects that haven't adopted SPDD scoping are
unaffected.

## Input Detection

Parse the input URL to determine the mode:

| Input pattern | Mode | Example |
|---|---|---|
| `...pull/123#discussion_r456` | Single | Specific comment URL |
| `...pull/123#pullrequestreview-789` | Batch (review) | All comments from that review |
| `...pull/123` | Batch (PR) | All unaddressed comments on PR |
| PR number only (e.g., `1164`) | Batch (PR) | All unaddressed comments on PR |

Extract `{owner}`, `{repo}`, `{pr_number}`, and optionally `{comment_id}`
or `{review_id}` from the URL.

**Optional additional context:**
- User may provide extra context after the URL
- Example: `/Dev10x:gh-pr-respond https://...#discussion_r456 Note that PR #1135 is merged`

---

## Mode A: Single Comment

**Trigger:** Input contains `#discussion_r{comment_id}`

### Step 1: Process the comment

**REQUIRED: Call `Skill(Dev10x:gh-pr-triage)`** — never triage
inline. Pass the comment URL (and any additional context).

**Per-comment enforcement (GH-463, GH-502):** This delegation
is mandatory for EVERY comment, including ones that appear
"obviously invalid" (e.g., bot-generated comments, trivially
wrong suggestions). The agent MUST NOT read the comment, judge
it inline, and post a reply directly. Even if you can determine
the verdict in 2 seconds, call `Skill(Dev10x:gh-pr-triage)` —
it ensures consistent reply format, audit trail, and workflow
state tracking. Three audit sessions (GH-463, GH-458, GH-502)
show the bypass happens when the agent rationalizes inline
triage as "equivalent" to skill delegation under context
pressure. It is not equivalent.

**Mandatory triage assertion (GH-502):** After processing each
comment, output this self-check before proceeding:

```
TRIAGE CHECK: comment r{id}
  Skill(Dev10x:gh-pr-triage) called: YES/NO
  Verdict: VALID/INVALID/QUESTION/OUT_OF_SCOPE
  If NO → STOP. Re-do with Skill() delegation.
```

If you cannot fill in "YES" for the Skill call, you have
bypassed delegation. Do not proceed — re-invoke the skill.

**Exception — author-confirmed validity:** If the PR author has
already replied to the comment explicitly acknowledging it as valid
(e.g., "good catch", "you're right", "will fix"), you MAY skip
triage and proceed directly to `Skill(Dev10x:gh-pr-fixup)` with
verdict `VALID`. This avoids redundant validation when the author
has already confirmed the comment warrants a fix. The skip applies
only when the author's reply is unambiguous — if there is any doubt,
delegate to triage as normal.

`Dev10x:gh-pr-triage` returns a verdict: `VALID`, `INVALID`, `QUESTION`, or `OUT_OF_SCOPE`.

- If **VALID** → **REQUIRED: Call `Skill(Dev10x:gh-pr-fixup)`
  immediately in the same turn** — do NOT report the verdict and
  wait for user input. The triage-to-fixup transition is atomic:
  verdict received → `Skill()` invoked, no pause between. Never
  implement fixes manually or post replies via raw `gh api`.
  The fixup skill handles the entire lifecycle: fix, commit, push,
  and reply.
- If **YAGNI** → triage has posted a reply naming the scope mismatch.
  Do NOT call `Dev10x:gh-pr-fixup` to harden the code. Surface the
  scope mismatch to the user (one `AskUserQuestion` gate listing
  the YAGNI bundle's comment IDs and the proposed removal) and
  route per their choice: remove the code in a single commit
  spanning all bundled threads, or defer the speculative feature
  to a follow-up ticket and close the threads. See § YAGNI
  routing below for the gate details.
- If **not VALID** (INVALID / QUESTION / OUT_OF_SCOPE) → triage
  has posted a reply but has NOT resolved the thread. Ask the
  user whether to resolve it (see Step 1b).

### Step 1b: Confirm thread resolution (INVALID / QUESTION / OUT_OF_SCOPE)

Fires only when `Dev10x:gh-pr-triage` returns INVALID, QUESTION, or
OUT_OF_SCOPE. VALID is handled by `Dev10x:gh-pr-fixup`; YAGNI is
handled by Step 1d (which owns its own thread-resolution path
per user choice).

Present the verdict and reason to the user and ask for confirmation
before resolving:

```
Comment r{comment_id} on {path}:{line}:
  Verdict: {verdict}
  Reason: {reason}
  Reply posted: ✅

Resolve this thread?
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
This blocks execution until the user responds. Options:
- **"Resolve"** — Resolve the thread via GraphQL
- **"Leave open"** — Keep the thread open (reply already posted)

### Step 1c: Hide obsolete comment (optional)

If the thread was resolved in Step 1b, offer to minimize the root
comment to reduce PR conversation noise:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **"Hide"** — Minimize the comment via GraphQL `minimizeComment`
  with classifier `OUTDATED`
- **"Skip"** — Leave the comment visible

**Skip this gate** if the thread was left open in Step 1b.

When hiding, use the comment's `node_id` (not numeric `id`).
Write the GraphQL mutation to a temp file and reference it with
`-F query=@file` to avoid shell quoting issues with `$` variables:
```bash
# Write mutation to temp file (use mcp__plugin_Dev10x_cli__mktmp)
# Then invoke:
gh api graphql -F query=@/tmp/Dev10x/gh/minimize.graphql \
  -f id='{node_id}' -f classifier='OUTDATED'
```

See `references/github_api.md` § Hiding (Minimizing) Comments.

### Step 1d: YAGNI routing (YAGNI verdict only)

Fires only when `Dev10x:gh-pr-triage` returns `YAGNI`. Triage has
already posted a reply naming the scope mismatch; this gate decides
how to close the bundled threads.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).

Present:
```
YAGNI bundle on PR #{pr_number}:
  JTBD: "{PR JTBD outcome phrase}"
  Out-of-scope code: {feature/module name}
  Bundled threads: r{id1}, r{id2}, r{id3} (N comments)
```

Options:
- **"Remove out-of-scope code" (Recommended)** — Create one removal
  commit closing all bundled threads. Delegate to
  `Skill(Dev10x:gh-pr-fixup)` with the bundled comment IDs and an
  instruction to revert/remove the speculative feature rather than
  harden it. Reply on each thread with the removal-commit reference
  using the bundled-reply template.
- **"Defer to follow-up ticket"** — Leave the code in place, create
  a tracking ticket via `Dev10x:ticket-create` capturing the
  speculative feature + the listed concerns, and reply on each
  thread linking the ticket. No fixup commit is created.
- **"Keep and harden each thread"** — Override the YAGNI verdict.
  Treat each comment as `VALID` and delegate to
  `Dev10x:gh-pr-fixup` per comment. Use only when the user
  intentionally wants the speculative feature shipped in this PR.

**Bundling guarantee:** When "Remove out-of-scope code" is selected,
all bundled comment IDs from the YAGNI verdict MUST be passed to
`Dev10x:gh-pr-fixup` in a single call with `bundled: true` metadata
(see § Bundled Fixup Mode). Splitting a YAGNI bundle into separate
removal commits defeats the audit signal that motivated the verdict.

### Step 2: Check for remaining comments

After processing the single comment, check for other unaddressed
root comments via
`mcp__plugin_Dev10x_cli__pr_comments(action="list", pr_number=<N>)`
and filter the returned list to entries whose `in_reply_to_id`
is null.

### Step 3: Offer to continue

If unaddressed comments remain, present them to the user:

```
Processed comment r{comment_id} → {verdict}

{N} unaddressed comment(s) remaining:
1. {author} on {path}:{line} — "{first_line_of_body}"
2. {author} on {path}:{line} — "{first_line_of_body}"

Continue to the next one?
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
This blocks execution until the user decides how to proceed. Options:
- **"Next comment"** — Process the next unaddressed comment (loop back to Step 1)
- **"Switch to batch mode"** — Triage all remaining and present a plan (jump to Mode B Step 2)
- **"Stop"** — End

---

## Mode B: Batch (PR or Review)

**Trigger:** Input is a PR URL, review URL, or PR number (no `#discussion_r`)

### Step 1: Collect unaddressed comments

**For a PR URL or number:** call
`mcp__plugin_Dev10x_cli__pr_comments(action="list", pr_number=<N>)`
and keep entries whose `in_reply_to_id` is null.

**For a review URL** (`#pullrequestreview-{review_id}`):
filter the same MCP result to comments whose
`pull_request_review_id` matches the review ID.

**Always check the review body for findings**, even when inline
comments exist. CI hygiene reviews from `claude[bot]` commonly
produce body-only findings, and inline threads may already be
resolved while the body contains unaddressed items.

**Body-only review handling:**

1. Extract the review body via
   `gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews`
   filtered by `review_id` (or scan all reviews if no review ID)
2. **Parse individual findings** from the body. Findings are
   identified by these patterns:
   - Bullet points starting with severity markers:
     `CRITICAL:`, `BLOCKING:`, `INFO:`, `WARNING:`, `NIT:`
   - Numbered items (`1.`, `2.`, etc.) with file:line references
   - Markdown list items (`- ` or `* `) that reference specific
     code locations (e.g., `mutations.py:115`)
   - Bold-prefixed items (`**[BLOCKING]**`, `**[INFO]**`)
3. Create one **synthetic comment** per parsed finding. Each
   synthetic comment carries:
   - `body`: the finding text (one bullet/item)
   - `path`: extracted file path (if present in the finding)
   - `line`: extracted line number (if present)
   - `review_id`: the parent review ID
   - `is_body_finding`: `true` (distinguishes from inline comments)
4. If the body contains no parseable findings but has non-empty
   text, treat the entire body as a single synthetic comment
   (fallback for unstructured review bodies)
5. Merge synthetic comments with any inline comments collected
   above, then continue to Step 2 (triage)

**Replying to body findings:** Since body findings have no inline
comment thread, replies are posted as top-level PR comments. Use
the MCP tool (no permission friction, structured response):

```
mcp__plugin_Dev10x_cli__pr_issue_comment(
    pr_number={pr_number},
    body="Re: {finding_summary}\n\n{reply}",
    repo="{owner}/{repo}",
)
```

This also covers replies to top-level bot comments (e.g., `claude[bot]`
findings posted via `gh pr comment`) that surface through
`check_top_level_comments` but have no review thread.

**Fallback** (only when the MCP server is unavailable):
```bash
gh api --method POST \
  repos/{owner}/{repo}/issues/{pr_number}/comments \
  -f body="Re: {finding_summary}\n\n{reply}"
```

If no inline comments AND no review body findings found → report
"No unaddressed comments" and stop.

### Step 2: Triage all comments (parallel)

Mark phase transition: `TaskUpdate(taskId=triage_task, status="in_progress")`

**REQUIRED: Dispatch parallel triage subagents.** Do NOT triage
comments sequentially in the main thread. Execute these steps:

1. Group comments into batches of up to 4
2. For each batch, dispatch all subagents in a **single tool-call
   block** using `Agent()` with `run_in_background=true`
3. Each subagent receives only its comment context (file, line,
   body, surrounding code) and returns: verdict, reason (1
   sentence), draft reply (2-3 sentences)
4. Collect results as notifications arrive
5. If more than 4 comments, dispatch the next batch as agents
   complete

**DO NOT SKIP parallel dispatch.** Sequential inline triage
defeats the purpose of this step — it increases processing time
linearly and blocks the main thread. Even for 2 comments, use
parallel agents. Each subagent MUST invoke
`Skill(Dev10x:gh-pr-triage)` — never inline the triage logic
within the subagent prompt itself (GH-502).

**Mandatory delegation in subagent prompt (GH-759 F2):**
Include this instruction in every triage subagent prompt:
"You MUST invoke `Skill(Dev10x:gh-pr-triage)` with the
comment URL. Never investigate inline or post replies
directly." Without this explicit instruction, subagents
bypass the skill and triage inline — 3 of 3 subagents
did so in the session that produced this finding.

Mark phase transition: `TaskUpdate(taskId=triage_task, status="completed")`

Present the full plan to the user as a table:

```
Found {N} unaddressed comments on PR #{pr_number}:
  JTBD: "{PR JTBD outcome phrase}"

| # | Author | File:Line | Summary | Verdict | Signal | Priority | Proposed Response |
|---|--------|-----------|---------|---------|--------|----------|-------------------|
| 1 | mike   | sender.py:19 | Use SubFactory | VALID | text | now | Change LazyFunction → SubFactory |
| 2 | mike   | fakers.py:21 | Randomize values | VALID | reaction:👍 | fast-follow | Tracked as test-quality enhancement |
| 3 | claude[bot] | dto.py:5 | TYPE_CHECKING | INVALID | text | n/a | 38+ files use this pattern |
| 4 | claude[bot] | tasks.py:12 | Missing type ann | INVALID | reaction:👎 | n/a | Declining — maintainer 👎 (no prose). Confirm? |
| 5 | mike   | feature.py:8  | Denorm drift | YAGNI | text | n/a | Bundle r{ids} → propose removal |

Bundles:
- YAGNI bundle "speculative-feature-X" (rows 5,7,8,9) → single
  removal commit proposed

Approve all, or specify which to modify/skip?
```

**Signal column (GH-314).** Every row carries a `Signal` value showing
whether the triage verdict came from prose in the comment body or from
an emoji reaction left by the maintainer. Reaction-sourced verdicts are
auditable before the approval gate — the reviewer can confirm or override
them with one click.

| Signal | Meaning |
|--------|---------|
| `text` | Verdict derived from comment prose (normal path) |
| `reaction:👍` | Maintainer 👍 (VALID lean, no prose) |
| `reaction:❤️` | Maintainer ❤️ (VALID lean, no prose) |
| `reaction:🚀` | Maintainer 🚀 (VALID lean, no prose) |
| `reaction:👎` | Maintainer 👎 (INVALID/decline lean, no prose) |
| `reaction:😕` | Maintainer 😕 (INVALID/decline lean, no prose) |

Reaction-sourced rows in the `Proposed Response` column include a
"Confirm?" suffix so the approver knows the verdict needs validation
before execution.

**Priority column (Finding 2, GH-297).** Every row carries a
`Priority` value so the batch plan no longer leaves defer-vs-handle
as a manual reviewer decision per comment.

| Priority | Applies to | Action at Step 4 |
|----------|-----------|------------------|
| `now`    | `VALID` comments that block correctness, security, or contract guarantees | Delegate to `Dev10x:gh-pr-fixup` in this batch |
| `fast-follow` | `VALID` comments that are non-blocking enhancements (test-coverage gaps, type narrowing, dedup, edge-case hardening, doc improvements, nice-to-have refactors) | Acknowledge on the thread, create or append to a fast-follow ticket via `Dev10x:ticket-create`, skip fixup in this batch |
| `n/a`    | `INVALID`, `QUESTION`, `OUT_OF_SCOPE`, `YAGNI` | Verdict already determines the action; priority does not apply |

**Heuristics for assigning `now` vs `fast-follow`:**

- Default to `now` when the comment names a correctness bug, a
  regression risk, a security hole, a missing migration safeguard,
  or a contract violation
- Default to `fast-follow` when the comment names a test gap, a
  type narrowing, a dedup, an admin edge case the PR did not
  introduce, a doc improvement, or a refactor opportunity
- When ambiguous, choose `now` and let the user downgrade to
  `fast-follow` during the Step 3 approval gate

The fast-follow rows roll up into a single batched ticket so the
reviewer does not have to thread each deferral by hand. Present the
proposed ticket title and body inline with the table for confirmation.

### Step 3: Get user approval

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
This blocks execution until the user approves the batch plan. Options:
- **"Approve all"** — Execute all proposed responses
- **"Review one-by-one"** — Present each for individual approval (like Mode A)
- **"Skip"** — Cancel batch

The user may also provide corrections in free text (e.g., "Comment 2 is not
valid, we use DataclassField" or "Comment 4: make it a question to the
reviewer").

### Step 4: Execute approved responses

Mark phase transition: `TaskUpdate(taskId=execute_task, status="in_progress")`

For each approved comment, route by **verdict + priority**:

- **VALID + priority=`now`** → **REQUIRED: Call
  `Skill(Dev10x:gh-pr-fixup)` immediately after verdict** — do
  NOT report the verdict and wait for user input between
  comments. The triage-to-fixup transition is atomic: verdict
  received → `Skill()` invoked, no pause. Never manually
  implement fixes or post replies via raw commands. The fixup
  skill handles the entire lifecycle.

  **Default cardinality is one fixup commit per comment.** When
  several VALID comments share a coherent fix, see the **Bundled
  Fixup Mode** section above — bundling is opt-in and requires
  every affected reply to use the hyperlinked bundled-reply
  template plus the post-groom SHA refresh sub-phase.
- **VALID + priority=`fast-follow`** → do NOT call
  `Dev10x:gh-pr-fixup` in this batch. Collect all fast-follow
  rows, draft a single follow-up ticket via
  `Dev10x:ticket-create` (one ticket per PR, listing each
  fast-follow comment link as an acceptance criterion), then
  reply on each thread acknowledging the deferral with a link
  to the new ticket:

  ```markdown
  Acknowledged — deferring to fast-follow [{ticket-id}]({url}).
  This PR's JTBD ({JTBD outcome}) ships without this change;
  the follow-up ticket tracks it.
  ```

  Do NOT resolve the thread automatically.
- **YAGNI** → respect the bundle. For each YAGNI bundle named in
  the batch plan, fire one **Step 1d-style YAGNI routing gate**
  (see Mode A § Step 1d) covering the whole bundle. The selected
  option (remove / defer / keep-and-harden) determines whether
  `Dev10x:gh-pr-fixup` is invoked once with all bundled comment
  IDs (`bundled: true`), whether a deferral ticket is created, or
  whether the comments fall back to individual VALID handling.
- **INVALID / QUESTION / OUT_OF_SCOPE** → post reply using MCP tool:
  ```
  mcp__plugin_Dev10x_cli__pr_comment_reply(
      pr_number={pr_number},
      comment_id={id},
      body="{reply}"
  )
  ```
  Do **NOT** resolve the thread automatically.

Report progress after each comment is processed.

Mark phase transition: `TaskUpdate(taskId=execute_task, status="completed")` then `TaskUpdate(taskId=resolve_task, status="in_progress")`

### Step 5: Thread resolution confirmation

After all replies are posted for non-VALID comments, collect threads that
could be resolved and present them individually to the user for confirmation.

**CRITICAL: Never auto-resolve threads.** The user supervising the PR review
needs to verify each triage decision. Auto-resolving hides threads on GitHub,
forcing the user to search through collapsed conversations.

Present each thread with its verdict and reason:

```
{N} threads replied to but not yet resolved:

1. r{id} on {path}:{line} — {verdict}: {reason}
   → Reply posted: "{first_line_of_reply}..."

2. r{id} on {path}:{line} — {verdict}: {reason}
   → Reply posted: "{first_line_of_reply}..."

Resolve these threads?
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
This blocks execution until the user confirms which threads
to resolve. Options:
- **"Resolve all"** — Resolve all listed threads
- **"Review one-by-one"** — Confirm each thread individually
- **"Leave all open"** — Keep all threads open (replies already posted)

**If "Review one-by-one":** For each thread, present:
```
r{id} on {path}:{line}
  Verdict: {verdict}
  Reason: {reason}
  Reply: "{reply_excerpt}"

Resolve this thread?
```
Options: "Resolve" / "Leave open"

**After confirmation**, resolve only the user-approved threads via GraphQL.

### Step 5b: Hide obsolete comments (optional)

After resolving threads, offer to minimize the resolved comments
to reduce PR conversation noise. This hides comment bodies on
GitHub, showing "This comment was marked as outdated" instead.

**Skip this step** if no threads were resolved in Step 5.

Collect all resolved threads' root comment `node_id` values:

```bash
gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 1) {
            nodes { id databaseId path body }
          }
        }
      }
    }
  }
}' -f owner='{owner}' -f repo='{repo}' -F pr={pr_number} \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
        | select(.isResolved)
        | .comments.nodes[0]]'
```

Present the resolved comments:

```
{N} resolved thread(s) can be hidden:

1. r{databaseId} on {path}:{line} — "{first_line_of_body}..."
2. r{databaseId} on {path}:{line} — "{first_line_of_body}..."

Hide these comments?
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
**Adaptive friction does NOT skip this gate** — at
`friction_level: adaptive`, the recommended option ("Hide all
resolved") is auto-selected, but the `AskUserQuestion` call still
fires and `mcp__plugin_Dev10x_cli__minimize_comments` MUST be
invoked on the resolved comments. Silently auto-advancing into
the shipping pipeline without calling `minimize_comments` is the
GH-208 regression and is caught by the
`gate6_fires_after_resolution` eval assertion.

Options:
- **"Hide all resolved" (Recommended)** — Minimize all resolved
  thread root comments with classifier `OUTDATED`
- **"Review one-by-one"** — Confirm each comment individually
- **"Skip"** — Leave all comments visible

**If "Review one-by-one":** For each comment, present:
```
r{databaseId} on {path}:{line}
  Body: "{body_excerpt}"
  Thread: resolved ✅

Hide this comment?
```
Options: "Hide" / "Skip"

**After confirmation**, minimize approved comments via GraphQL:
```bash
gh api graphql -f query='
mutation($id: ID!, $classifier: ReportedContentClassifiers!) {
  minimizeComment(input: {
    subjectId: $id, classifier: $classifier
  }) {
    minimizedComment { isMinimized minimizedReason }
  }
}' -f id='{node_id}' -f classifier='OUTDATED'
```

See `references/github_api.md` § Hiding (Minimizing) Comments.

### Step 6: Summary

After all comments are processed, report:

```
Batch complete: {N} comments processed
- {x} VALID-now (fixup commits created)
- {f} VALID-fast-follow (deferred to ticket {ticket-id})
- {g} YAGNI (bundled into {b} removal commit(s) | deferred to ticket {id})
- {y} INVALID (replied)
- {z} QUESTION (answered)
- {w} OUT_OF_SCOPE (acknowledged)
- {r} threads resolved (user-confirmed)
- {h} comments hidden (minimized)
- {u} threads left open
```

---

## Post-Response Continuation

After all comments are processed (Mode A or Mode B), if fixup commits
were created during this session, offer to continue the full shipping
pipeline.

### Parent Context Detection

**Before offering the shipping pipeline, check if a parent
orchestrator (e.g., `Dev10x:work-on`) is managing the shipping
sequence.** When invoked as a delegated skill via `Skill()` from
a parent that has its own shipping pipeline tasks (groom, push,
monitor, ready), skip the Post-Response Continuation gate entirely
and return control to the parent. The parent's remaining tasks
cover the same steps — running them here creates duplicates.

**Detection heuristic:** Call `TaskList`. If tasks exist with
subjects matching the parent's shipping pipeline (e.g., "Groom
commit history", "Monitor CI", "Mark PR ready"), a parent
orchestrator owns the pipeline. Return without offering the
continuation gate.

**When no parent is detected** (standalone invocation), proceed
with the gate below.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **"Full shipping pipeline" (Recommended)** — Execute the complete
  post-response shipping sequence. **REQUIRED: Use `Skill()` for
  each step** — never run raw git/gh commands directly:
  1. `Skill(Dev10x:git-groom)` — squash fixup commits
  2. **Post-Groom SHA Refresh** — PATCH any session-posted
     replies that referenced pre-groom SHAs. See the
     **Bundled Fixup Mode → Post-Groom SHA Refresh** section
     above. Use `mcp__plugin_Dev10x_cli__pr_comments(action="edit")`,
     never raw `gh api -X PATCH`. Skip when no replies were
     posted this session.
  3. `Skill(Dev10x:git)` — push with `--force-with-lease`
  4. `Skill(Dev10x:gh-pr-monitor)` — watch CI after force push
  5. **CI guard (GH-684):** Only after CI passes, run
     `gh pr ready` to mark the PR ready for review. Do NOT
     run `gh pr ready` before CI is green — this was the #1
     bypass pattern: marking ready then discovering CI failures.
     Also verify no unresolved review threads remain before
     marking ready.
  6. If CI passes and no new comments → merge via
     `Skill(Dev10x:gh-pr-merge)` — NEVER raw `gh pr merge`
     (GH-759 F3). The skill validates 8 pre-merge conditions
     including unaddressed review comments that raw merge
     bypasses.
- **"Groom + push only"** — Groom and push, but stop before
  monitoring and merge
- **"Stop"** — End without pushing

This eliminates the manual multi-step chain that was required
after every respond session. The full pipeline handles the entire
groom → push → ready → monitor → merge lifecycle.

**Skip this gate** if no fixup commits were created (e.g., all
comments were INVALID and only replies were posted).

**Solo-maintainer mode:** When the project playbook defines a
solo-maintainer override (no external reviewers), the full
pipeline auto-merges after CI passes without waiting for
external approval.

---

## Tools

Prefer MCP tools for PR comment operations; reach for `gh api`
only for endpoints that have no MCP wrapper (review listings,
GraphQL mutations).

| Operation | Tool |
|---|---|
| List comments | `mcp__plugin_Dev10x_cli__pr_comments(action="list", pr_number=N)` |
| Fetch one comment | `mcp__plugin_Dev10x_cli__pr_comments(action="get", comment_id=ID)` |
| Reply to thread | `mcp__plugin_Dev10x_cli__pr_comment_reply(pr_number=N, comment_id=ID, body="...")` |
| Filter root-only | Filter MCP result on `in_reply_to_id == null` |
| Resolve thread | See `references/github_api.md` GraphQL section |
| List reviews | `gh api repos/{owner}/{repo}/pulls/{N}/reviews` (no MCP) |
| Minimize comment | `gh api graphql` minimizeComment (no MCP) |

---

## Decision Flow

```
Input URL
    │
    ├─ Has #discussion_r{id} ──► MODE A (single)
    │       │
    │       ├── Dev10x:gh-pr-triage → verdict
    │       ├── if VALID → Dev10x:gh-pr-fixup
    │       ├── if not VALID → reply posted, ask user to resolve
    │       ├── if resolved → offer to hide (minimize) comment
    │       ├── check remaining
    │       └── offer: next / batch / stop
    │
    └─ PR URL / review URL / number ──► MODE B (batch)
            │
            ├── collect unaddressed comments
            ├── triage all (draft, don't post)
            ├── present plan table
            ├── get user approval
            ├── execute approved responses (reply only, no resolve)
            ├── collect non-VALID threads → ask user to confirm resolution
            ├── hide resolved comments → ask user to confirm hiding
            └── summary
```

## Integration

```
Dev10x:gh-pr-monitor → Dev10x:gh-pr-respond (this skill)
                 ├── Dev10x:gh-pr-triage
                 └── Dev10x:gh-pr-fixup
                      └── Dev10x:git-fixup
```

**Standalone usage:**
```bash
# Single comment
/Dev10x:gh-pr-respond https://github.com/owner/repo/pull/123#discussion_r456

# Single comment with context
/Dev10x:gh-pr-respond https://github.com/owner/repo/pull/123#discussion_r456 Note that PR #1135 is merged

# Batch — all unaddressed comments on PR
/Dev10x:gh-pr-respond https://github.com/owner/repo/pull/123

# Batch — all comments from a specific review
/Dev10x:gh-pr-respond https://github.com/owner/repo/pull/123#pullrequestreview-789

# Batch — PR number only
/Dev10x:gh-pr-respond 1164
```

**Called by Dev10x:gh-pr-monitor:**
```
Dev10x:gh-pr-monitor detects new comments →
  delegate to Dev10x:gh-pr-respond with PR URL (batch mode)
```

## References

### references/github_api.md

Contains GitHub API documentation for:
- Listing PR comments
- Fetching single comments
- Creating replies
- Resolving review threads (GraphQL)
- Hiding (minimizing) comments (GraphQL)
- Filtering and querying
