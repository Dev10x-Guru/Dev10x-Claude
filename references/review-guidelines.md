# Claude Code Review Guidelines

Review **workflow** rules — how to conduct reviews, manage threads,
write summaries, and interact with authors. For **what to check**
in code, see the domain-specific agent specs in `.claude/agents/`.

## Approval State Guard (GH-993)

Before requesting review (or re-review) on a PR, the
`Dev10x:request-review` skill family **must** check the PR's
current review state to avoid pinging reviewers on already-approved
PRs.

**Decision rule:**

1. Fetch state via `gh pr view N --json reviewDecision,reviews,headRefOid`
   (or the equivalent MCP tool).
2. If `reviewDecision == "APPROVED"` AND the latest review's
   `commit.oid` matches `headRefOid` → PR is approved on the
   current HEAD. **Short-circuit** the request and offer
   `Dev10x:gh-pr-merge` instead via `AskUserQuestion`.
3. If `reviewDecision == "APPROVED"` but newer commits have
   invalidated the approval (review SHA != HEAD SHA) →
   proceed with re-request, but **filter out** any reviewer whose
   most recent review on the current HEAD is already `APPROVED`.
4. Otherwise (`CHANGES_REQUESTED`, `REVIEW_REQUIRED`, or `null`) →
   proceed normally.

**Bypass:** Callers may pass `bypass_approval_check: true` (or a
`--force` flag) to skip the guard. This is intended for explicit
internal flows — e.g., `Dev10x:gh-pr-monitor` Phase 3 re-request
after fixups, where the caller has already validated state. Do
not bypass for direct user invocations.

**Why?** Re-pings on approved PRs create reviewer fatigue and
churn — the supervisor's next action is merge, not another review
cycle. The guard turns a mid-flow noise event into an explicit
choice between merge and force-request.

The guard applies to:
- `Dev10x:request-review` (orchestrator) — Step 1.5 precheck
- `Dev10x:gh-pr-request-review` — Pre-flight Approval State Check
- `Dev10x:slack-review-request` — Step 0 precheck

## Review Workflow

1. Check existing review comments (mcp__github__get_pull_request_review_comments)
   to avoid duplicating feedback
2. Check for previous summary comments (`gh pr view {PR_NUMBER} --json comments`)
   to identify obsolete summaries
3. Analyze current diff (`gh pr diff`)
4. For each previous Claude Code Review thread:
   - Fixed/removed → reply "Addressed" (do NOT resolve — leave for human)
   - Persists in unchanged code → reply "Still applies"; do NOT duplicate
   - Changed but issue remains → reply with update
5. Use inline comment tools ONLY for NEW issues
6. Hide obsolete review summaries before posting the new one:
   a. Query `reviewThreads` via `gh api graphql` — for each thread,
      check `isResolved` and group by `pullRequestReview.databaseId`
   b. For each previous Claude review with a non-empty body:
      - ALL threads `isResolved: true` → minimize as OUTDATED
      - ANY thread unresolved → leave visible
      - Review has NO inline threads (summary-only) → minimize
   c. Minimize: `minimizeComment(input: {subjectId: "<node_id>",
      classifier: OUTDATED})`
   d. Skip the current review cycle's own review
   e. Thread resolution must come from the human supervisor —
      the reviewer MUST NOT resolve threads to trigger this gate
7. Create ONE summary review comment (`gh pr review --comment`) with:
   - High-level observations and quality assessment
   - Cross-cutting concerns not tied to specific lines
   - Acknowledgment of addressed issues
   - DO NOT repeat inline comment content
8. Use COMMENT status (not REQUEST_CHANGES or APPROVE)
9. If inline comments were posted, convert PR to draft:
   `gh pr ready --undo $PR_NUMBER`
   - Prevents noisy re-reviews on fixup commits
   - Author marks "Ready for review" when fixes are complete
   - Do NOT convert if the review was clean (no inline comments)

## Workflow Cross-Awareness

| Workflow                   | Trigger              | Scope                          |
|----------------------------|----------------------|--------------------------------|
| `pr-hygiene-review.yml`   | PR opened/ready      | PR metadata (title, body, commits) |
| `claude-code-review.yml`  | PR opened/ready/sync  | Code quality, architecture     |
| `claude.yml`              | @claude mention      | Interactive assistance         |
| `claude-memory-review.yml`| PR merged            | Lessons learned extraction     |

**Code review must NOT provide feedback on** PR title format, PR body
format, or commit message structure — these are `pr-hygiene-review`
scope.

*Why?* Prevents duplicate feedback between workflows.

### Hygiene Review Severity Labels

- **REQUIRED**: Breaks tooling (missing gitmoji, no `Fixes:` link,
  fixup commits remaining). Advisory — does not auto-gate merge,
  but authors should address or justify before merging.
- **RECOMMENDED**: Style preferences (compact commit list, ticket ID
  in title, JTBD wording)

When no tracked issue exists, `Fixes: none — self-motivated refactor`
is an accepted `Fixes:` value.

## Scope & Noise

- Focus on lines changed in the PR diff
- Issues in **unchanged** code → "pre-existing, out of scope"
  (informational, not blocking)
- NEVER repeat feedback from previous review cycles
- Group related issues by topic; keep summary brief
- Each inline comment references file path and line number
- **Bootstrapping exception** — when a PR introduces a new rule,
  the PR itself may violate it because the rule wasn't enforced
  when the PR was submitted. Flag as informational, not blocking.

## Stacked PR Review

When the PR body contains "Stacked on #N" or "Depends on #N":
1. Note the dependency in the review summary
2. Focus on files/changes unique to the current PR
3. Use `gh pr view <base-pr>` to understand base PR scope
4. Flag interleaved commits from base and current PR

## Context-Aware Review Depth

| Context        | Focus                                    | Avoid                                |
|----------------|------------------------------------------|--------------------------------------|
| Production     | All standards                            | Bikeshedding                         |
| POC/Test       | Does it work? Security. Broken logic.    | YAGNI, error handling, edge cases    |
| Refactor       | Behavior preservation                    | New features, scope creep            |
| Infrastructure | Behavioral changes, help text accuracy   | Questioning stated design intent     |

### POC Detection

Check PR title (🧪, "POC", "test", "demo"), file paths (`test`,
`poc`), and description ("temporary", "exploratory"). If POC:
- Start summary with "Reviewing as POC/test code with relaxed standards"
- Review only: bugs, security, integration issues

### Infrastructure Reviews

- Trust design decisions stated in PR title/body
- Frame concerns as "consider whether" not "this is wrong"
- If author clarifies intent, acknowledge and close

### Author Design Clarifications

When an author explains flagged behavior is intentional:
1. Verify PR title/body supports the claim
2. Acknowledge and close the thread
3. Never re-raise in subsequent cycles
4. Never require re-explanation after force-pushes

**Skill delegation example**: when an author states that a skill invocation
name (e.g., `pr:create`) references an external skill at `~/.claude/skills/`,
verify no `skills/*/SKILL.md` with that name exists in this repo, then close.
Do NOT re-flag the name in the next review round.

## Summary Comment Strategy

- ONE summary per review cycle (not per commit)
- **Only post if** there are new issues or material changes to review
- **If there are no new issues, post NO review at all.** An empty-body
  COMMENTED review adds noise without value.
- After fixes: post ONE brief acknowledgment, not per-file comments
- After 3+ summaries saying "looks good": do NOT post another

### Re-Review Summary Structure

```markdown
## Review Summary (Round N)

### Addressed since last review
- [list items that were fixed]

### Remaining issues
- [only genuinely new or previously unfixed items]
```

Round numbering tracks review invocations, not author fix commits.
Each time Claude is triggered to review (e.g., on `synchronize`),
that is a new round — even if the author pushed multiple fix commits
between rounds.

## Context Rot Mitigation

### Before Each Re-Review

1. Re-read PR description; don't rely on memory
2. Diff against previous review state; focus on what changed
3. Verify resolved threads are actually fixed
4. Read ALL author replies; build a "rejected suggestions" list

### During Re-Review

5. No zombie comments — don't re-raise intentionally rejected issues
6. Batch related feedback into ONE comment with all locations
7. Acknowledge progress explicitly
8. After 3 rounds: focus on correctness only (bugs, security)
9. Read actual file at HEAD, not diff context (force-pushes shift lines)

## Multi-Commit Review Awareness

1. First review: flag issues in current code
2. After new commits: check if previous issues are now fixed
3. Acknowledge fixes; only flag new or persistent issues
4. Check existing threads before creating new ones

## Code Suggestions Format

Use GitHub suggestion syntax for committable fixes:

```suggestion
fixed code here
```

- Single-line: comment on line N
- Multi-line: set start_line=N, line=M
- Add explanation before the suggestion block
- Use for straightforward fixes; describe approach for complex changes
- Do NOT use suggestion blocks for non-code changes (permissions,
  file renames, `git mv`). Use plain text instructions instead.

## Review Comment Format & JTBD Variants

Structure findings as **[REQUIRED/RECOMMENDED]** — [title], explanation,
rule reference, fix. For JTBD grammar: third-party outcomes like "**so**
reviewers can catch issues" (per `git-jtbd.md`) are acceptable—mark as
RECOMMENDED, not REQUIRED. Canonical first-person "**so I can**" is
preferred but not mandatory when third-party intent is clear.

## Positive Validation

When a PR demonstrates excellent practices:
- Call out strengths with file:line references
- Not every PR needs change requests
- One positive summary per resolved cycle

## Avoid Valueless Suggestions

- NEVER suggest code identical to the original
- NEVER suggest formatting changes (linters handle this)
- VERIFY character-by-character before suggesting
- Only suggest: bugs, security, architecture, performance, logic,
  naming
- When in doubt: skip it

## Courtesy-Fixup Disposition (GH-323)

`Dev10x:gh-pr-review` classifies each finding with a
**courtesy-fixup disposition**: mechanical, unambiguous findings
may be pushed as `fixup!` commits by the reviewer, with consent,
instead of posting an inline comment. The scope gate (Step 6b)
fires only when courtesy-fixable findings exist; reviews with no
mechanical changes see no extra interaction.

### Design decisions

**Batch vs per-finding confirmation**: Batch — all courtesy-fixable
findings are presented in a single `AskUserQuestion` so the
reviewer authorizes the full push scope in one interaction. A
"Pick individually" option is available for granular control.

**Default on/off**: The courtesy-fixup classification runs on
every review by default. The scope gate (Step 6b) fires only when
there are courtesy-fixable findings, so reviews with no mechanical
fixes see no additional interaction.

**friction_level interaction**: The Step 6b gate is `ALWAYS_ASK`
(fires at all friction levels including `adaptive`). Rationale:
pushing to another author's branch is an outward-facing action
with real branch-state consequences. Auto-advancing past this gate
at `adaptive` would push commits the reviewer never explicitly
authorized. The gate is the guardrail, not friction.

See [`references/courtesy-fixup-disposition.md`](courtesy-fixup-disposition.md)
for criteria, examples, reply framing, and the required "feel free to amend or drop" language.
