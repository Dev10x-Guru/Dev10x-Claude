# Review Routing — One Subagent per Reviewer Spec (GH-1741)

How a code review splits a change across reviewer specs. Two callers
follow these rules:

| Caller | When | Where the diff comes from |
|--------|------|---------------------------|
| CI — `.github/claude/prompts/code-review.core.md` Step 3 | On a PR, after the ready-for-review flip | `.claude-ci/pr-context/patches/<path>.patch` |
| Local — `dev10x:review` Step 4 | On a branch, before its first push | Inlined into each subagent prompt by the skill |

The callers differ only in how a subagent gets its diff. Routing,
dispatch and merging are the same, and this file is where they are
written down. `tests/test_claude_ci_prompts.py` (`TestSharedRouting`)
checks that the CI prompt still states the rules below, so a change to
one side that misses the other fails the suite.

## Why one subagent per spec

One agent that holds the whole diff plus every reviewer spec skims the
specs it reads last, and reviews one file at a time when it could
review them in parallel. A subagent that holds one spec and only the
files routed to it reads that spec in full. Each spec also sets its
own model tier, which a single shared agent cannot honour.

## Rule 1 — Route by the INDEX.md table

`.claude/rules/INDEX.md` § "File Patterns -> Agents" is the only
routing source. Neither caller keeps its own list of agents
(GH-1619: a copied list drifted and left two reviewers out of every
CI review).

1. For each changed file, take every row whose File Pattern matches
   it.
2. The row's Primary Agent column names that file's agents. A file
   can match several rows, and so reach several agents.
3. Group the files by agent. Each agent gets one subagent with all of
   its files.
4. Deleted files are not routed. A renamed file is routed by its new
   path.

## Rule 2 — Dispatch only registered agents

Dispatch an agent only when this session has its spec:

- a project spec at `.claude/agents/<name>.md`, dispatched as
  `<name>`; or
- a plugin-distributed spec at `agents/<name>.md`, dispatched as
  `dev10x:<name>` (for example `dev10x:reviewer-migration`).

When a matched row names an agent with no spec, the orchestrator
reviews those files itself and says so in the summary.

**A repo with no `.claude/rules/INDEX.md`** has no routing table. Route
instead by the `Triggers:` patterns in the plugin's `agents/reviewer-*.md`
descriptions — `dev10x:reviewer-celery`, `dev10x:reviewer-e2e`,
`dev10x:reviewer-frontend`, `dev10x:reviewer-graphql`,
`dev10x:reviewer-migration`, `dev10x:reviewer-signals`,
`dev10x:reviewer-test-flaky`, `dev10x:reviewer-test-patterns`. Files
that match none of them are reviewed by the orchestrator against
`references/review-checks-common.md`.

## Rule 3 — Dispatch in one message, in the foreground

- Dispatch every matched subagent in ONE message so they run in
  parallel.
- Run them in the foreground. In CI, where background tasks are
  disabled, each call returns the subagent's full report in that same
  message, so the orchestrator never ends its turn to wait. A session
  that hands the calls back as background launches delivers reports
  later instead
  (`references/orchestration/subagent-status-protocol.md` § Delivery
  channel): merge nothing until every launched subagent has reported,
  and treat one still running as pending, never as failed.
- Only dispatch agents for domains with changed files.
- When a domain has more than ~15 changed files, split it across two
  subagents by directory.
- Do not override the model. Each spec's `model:` frontmatter sets
  its tier.

## Rule 4 — What every subagent prompt carries

1. The list of changed files for its domain, and how to see each
   file's diff (the caller's column in the table above).
2. Its Required Reading rule files, as listed in the agent spec.
3. The coverage-first instruction, verbatim:

   > Report every issue you find, including ones you are uncertain
   > about or consider low-severity. Do not filter for importance or
   > confidence — the orchestrator verifies and ranks findings. For
   > each finding include file:line, severity (CRITICAL / WARNING /
   > INFO), confidence, and a one-sentence rationale.

The subagent reports; it never edits a file, posts a comment, or
dispatches another agent.

## Rule 5 — Merge in the orchestrator

When the subagents return, the orchestrator — never a subagent:

1. Deduplicates findings that more than one agent raised on the same
   file:line, keeping the highest severity and the highest
   confidence.
2. Checks every finding against `references/review-checks-common.md`
   and drops false positives, noting the dropped count in the
   summary.
3. Filters by confidence and severity. The caller sets the threshold:
   CI posts CRITICAL and WARNING and includes INFO only when it is
   clearly actionable; `dev10x:review` applies its confidence
   threshold.
4. Verifies each surviving finding against the actual code (Read the
   file at the cited line) before reporting it.

Cross-cutting checks (dead code, parameter-change call sites, scope)
stay with the orchestrator, because they need the whole change rather
than one domain's files.

## Changing these rules

Edit this file and `code-review.core.md` Step 3 in the same PR, then
update `skills/review/references/domain-dispatch.md` if the local
prompt template is affected. CI reads `references/**` from the base
branch (`.claude/rules/claude-ci-cost.md` § Where each file comes
from), so a new rule here reaches CI only through the prompt text.
