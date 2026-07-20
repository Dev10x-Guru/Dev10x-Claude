# Essential Conventions

Universal rules for every session. Detailed guides live in
`references/` and load on-demand via skills.

## Branch & PR Targeting

- **Feature PRs** target the detected base branch — `detect-base-branch.sh`
  prefers `develop`/`development`, falls back to `main`/`master`/`trunk`
- **Release PRs** target `main` only via merge from `develop`
- Branch format: `username/TICKET-ID/short-description`
- Worktree branch format: `username/TICKET-ID/worktree-name/short-description`
- **Self-motivated work** (no ticket): Use `username/short-description` and
  set `Fixes: none — self-motivated` in PR body (see `git-pr.md`)

## Commit Format

- Title: `<gitmoji> <TICKET-ID> <outcome-focused description>`
- Max 72 characters per line (title and body)
- Outcome-focused: "Enable X" not "Add X" — describe what
  the change enables, not what was implemented
- One logical change per commit (atomic commits)
- No "Co-Authored-By: Claude" footer
- Full format guide: `references/git-commits.md`

## PR Body

- First paragraph: JTBD Job Story (`**When** ... **[actor] wants to** ...
  **so [beneficiary] can** ...`) — third-person concrete domain roles
  (see `references/git-jtbd.md` § Choosing the Actor)
- Optional: Compact commit list (one line per commit)
- Last line: `Fixes:` link (issue URL or `none — self-motivated`)
- Do NOT add extra separators (`---`) between Job Story and
  commit list — `create-pr.sh` template handles separators
- Full guide: `references/git-pr.md`

## Decision Gates & Orchestration

Skills with blocking decision points MUST use `AskUserQuestion` tool calls,
never plain text questions. This ensures:
- Execution blocks until the user responds (not auto-progressed)
- Options are clickable and structured (not free-text)
- The skill's documented flow is respected

Mark every decision gate in SKILL.md with:
**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)

Plain text questions allow agents to silently substitute default answers,
breaking skill orchestration. See `.claude/rules/skill-gates.md` for pattern.

This rule applies **globally** — not only inside loaded skills. When
presenting A/B design choices, architectural trade-offs, or strategy
options between skill invocations, use `AskUserQuestion` with structured
options. Queue decisions per `references/task-orchestration.md` (Batched
Decision Queue pattern) and present them in a single batch when all
tasks are blocked.

## Task List Invariant (GH-149)

**The session task list must never be empty.** When a Dev10x skill
completes its last work item, it MUST leave at least one open task on
the list — by default, a `Verify AC` task that summarizes what was
shipped and prompts the supervisor to confirm completion before the
session is closed.

`Dev10x:work-on` already enforces this for its multi-phase plans (see
`skills/work-on/instructions.md` § Phase 4). This rule lifts the same
invariant to a universal contract for **every** Dev10x skill that
mutates the task list, including standalone invocations that finish a
discrete unit while a broader plan is in flight.

**Required `Verify AC` task content:**

- PR URL(s) created or updated during the session
- One-line summary per change shipped
- Confirmation of CI status (passing / pending / failing)
- Confirmation that no review comments are unaddressed
- Any ACs/DoD items still requiring manual sign-off

**Why this matters:**

- A new prompt landing on an empty task list competes for attention
  with whatever is already in flight; with the task list populated,
  the new prompt lands as a TODO under the existing plan
- The supervisor confirms completion explicitly rather than the agent
  declaring itself done
- The supervisor can extend scope by adding tasks BEFORE `Verify AC`
  without restarting the session

**Behavior when skill execution completes:**

1. If a `Verify AC` task already exists (created by `Dev10x:work-on`
   or `Dev10x:verify-acc-dod`), leave it `pending` and STOP
2. If no `Verify AC` task exists AND the task list would otherwise be
   empty, create one before declaring completion:
   ```
   TaskCreate(subject="Verify AC and close session",
       description="Summary of changes: <PR URLs, commits, CI status>",
       activeForm="Verifying AC")
   ```
3. Never mark `Verify AC` `completed` autonomously — the supervisor
   completes it explicitly during `Dev10x:verify-acc-dod` or
   `Dev10x:session-wrap-up`

## Reference Documents

| Document | Topic | Loaded by |
|----------|-------|-----------|
| `references/git-commits.md` | Commit format, gitmoji, atomic commits | `Dev10x:git-commit` skill |
| `references/git-jtbd.md` | Job Story format, anti-patterns | `Dev10x:jtbd` skill |
| `references/git-pr.md` | PR body, grooming, review feedback | `Dev10x:gh-pr-create` skill |
| `references/review-guidelines.md` | Review workflow, threads, summaries | `Dev10x:gh-pr-review` skill |
| `references/review-checks-common.md` | False positive prevention, verification | Review agent specs |
