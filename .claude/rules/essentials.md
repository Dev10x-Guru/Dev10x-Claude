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
- Use the project or ticket language for Job Stories and BDD scenarios.
  For Gherkin-derived keywords, use Cucumber's language reference:
  https://cucumber.io/docs/gherkin/languages/
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

### When the task tools are absent (GH-1055)

`TaskCreate` / `TaskGet` / `TaskUpdate` / `TaskList` / `TodoWrite`
ship by default only on Claude 3.x, Opus 4–4.7, Sonnet 4–4.6 and
Haiku 4.5. On every newer model, and on any model ID Claude Code
does not recognise (a gateway-served custom name), they are left
out unless the user opts in. So a session with no task tools is a
supported configuration, not a broken one.

The task list is a **mechanism**. What it serves is a **purpose**:
the supervisor can see work in flight, a new prompt lands against
that work instead of competing with it, and the agent never
declares itself done. Losing the mechanism does not retire the
purpose — it moves to the transcript:

1. State the plan as a written checklist in the reply, in the same
   order the tasks would have had, and restate what changed as
   each item completes.
2. Close with an explicit `Verify AC` section carrying the content
   listed above — PR links, per-change summary, CI status,
   outstanding review comments, unsigned AC items.
3. Never announce the work complete on your own. The `Verify AC`
   section ends the turn; the supervisor's confirmation ends the
   session.

**Never stop because the tools are missing.** Refusing to run is
the one wrong answer — it makes the plugin unusable on the models
it will most often meet.

**Be honest that this is a degradation, not a substitute.** A
supervisor cannot insert a task before `Verify AC` in a
transcript, and nothing in it survives a compaction boundary.
What does survive is what plan-sync persisted: the
`plan_sync_*` tools are MCP tools rather than task tools, so
`branch` / `tickets` identity and the `session_adoption`
staleness computation keep working unchanged. Only the task
mirror is lost — the `TaskUpdate` and `TaskCreate|TaskUpdate`
matchers in `hooks/hooks.json` never fire, so `plan.yaml` holds
no tasks. Any reader of `plan.tasks` therefore sees a session
with no task tools as indistinguishable from a fresh one, and
must not treat the emptiness as evidence of anything else.

## Reference Documents

| Document | Topic | Loaded by |
|----------|-------|-----------|
| `references/git-commits.md` | Commit format, gitmoji, atomic commits | `Dev10x:git-commit` skill |
| `references/git-jtbd.md` | Job Story format, anti-patterns | `Dev10x:jtbd` skill |
| `references/git-pr.md` | PR body, grooming, review feedback | `Dev10x:gh-pr-create` skill |
| `references/review-guidelines.md` | Review workflow, threads, summaries | `Dev10x:gh-pr-review` skill |
| `references/review-checks-common.md` | False positive prevention, verification | Review agent specs |
