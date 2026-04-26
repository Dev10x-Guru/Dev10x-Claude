<p align="center">
  <a href="https://github.com/Dev10x-Guru/dev10x-claude/releases"><img src="https://img.shields.io/github/v/release/Dev10x-Guru/dev10x-claude?style=for-the-badge&color=blue" alt="GitHub Release"></a>
  <img src="https://img.shields.io/badge/skills-69-green?style=for-the-badge" alt="69 Skills">
  <img src="https://img.shields.io/badge/agents-21-purple?style=for-the-badge" alt="21 Agents">
  <img src="https://img.shields.io/badge/hooks-6-orange?style=for-the-badge" alt="6 Hooks">
  <a href="https://github.com/Dev10x-Guru/dev10x-claude/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Dev10x-Guru/dev10x-claude?style=for-the-badge&color=green" alt="License"></a>
</p>

<p align="center">
  <a href="https://github.com/Dev10x-Guru/dev10x-claude/stargazers"><img src="https://img.shields.io/github/stars/Dev10x-Guru/dev10x-claude?style=flat-square&logo=github" alt="GitHub stars"></a>
  <img src="https://img.shields.io/badge/clones-20k+-blue?style=flat-square" alt="GitHub clones">
  <a href="https://github.com/Dev10x-Guru/dev10x-claude/issues"><img src="https://img.shields.io/github/issues/Dev10x-Guru/dev10x-claude?style=flat-square" alt="GitHub issues"></a>
  <img src="https://img.shields.io/badge/python-3.11+-yellow?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+">
</p>

<p align="center">
  <a href="https://dev10x.guru">
    <img src="https://dev10x.guru/og-image.png" alt="Dev10x — Stop babysitting your AI. Start supervising." width="800">
  </a>
</p>

<p align="center">
  <a href="https://dev10x.guru">Dev10x.guru</a> | <a href="https://www.skool.com/Dev10x-1892/about">Join Community</a>
</p>

---

# Dev10x Claude Plugin

Stop babysitting your AI. Start supervising it.

---

A Claude Code plugin that gives your AI pre-approved workflows,
self-correcting guardrails, and a complete scope-to-merge pipeline —
so you can supervise in 5-minute windows instead of hovering over
every command.

[![asciicast](https://asciinema.org/a/vAEDMseToIBk35wo.svg)](https://asciinema.org/a/vAEDMseToIBk35wo)

## The problem with AI coding assistants

**Permission friction kills autonomy.** Every ad-hoc bash command
triggers a permission prompt. Every prompt pulls you back to the
terminal. Your AI can write code, but it can't ship a commit
without asking you 15 times.

**Progress is invisible.** You walk away for 10 minutes and come
back to a wall of terminal output. Or a stalled session waiting
for approval. No way to tell at a glance if things are on track.

**Attention doesn't batch.** You want to give 5 minutes of
direction, check in during coffee, and move on. Instead you're
hovering — approving every shell command, every file write, every
git operation.

## How Dev10x solves this

### Pre-approved workflows, not ad-hoc scripts

67 skills encapsulate complete dev workflows as slash commands.
`/commit` handles gitmoji, ticket reference, and benefit-focused
title — all through pre-approved tool calls that never trigger
permission prompts.

When Claude uses `/Dev10x:gh-pr-create` instead of raw `gh` commands, every
step matches an allow rule. Zero interruptions.

### Guardrails that teach, not just block

14 hooks across 5 lifecycle events intercept dangerous patterns
*before* they execute — and redirect the AI toward the approved
path:

- **`validate-bash-command`** catches `&&` chaining, inline
  `python3 -c`, and other patterns that break allow rules →
  teaches separate calls and `uv run --script`
- **`validate-edit-write`** blocks `.env` file creation and
  enforces safe file editing patterns
- **`ruff-format-python`** auto-formats Python files after every
  Edit/Write — no manual formatting step needed
- **`task-plan-sync`** persists task state to survive context
  compaction across long sessions

The hooks carry educational messages. The AI learns from each
block. By mid-session, it stops triggering them entirely.

### Orchestration that finishes what it starts

Long AI sessions drift. The agent forgets the plan, skips steps,
uses raw CLI commands instead of skill wrappers, and produces PRs
missing ticket links, Job Stories, or CI verification. You come
back to a branch that *looks* done but isn't merge-worthy.

[`Dev10x:work-on`](skills/work-on/SKILL.md) solves this with a
four-phase orchestrator — parse inputs, gather context in
parallel, build a supervisor-approved plan from a YAML playbook,
then execute with enforced skill routing:

- **Playbook-driven plans** — every work type (feature, bugfix,
  PR continuation, investigation) has a default play with ordered
  steps. Override per-project via YAML without touching plugin
  code.
- **Skill routing enforcement** — a hard-wired table maps every
  shipping action (commit, push, PR, CI monitor, groom) to its
  skill wrapper. The agent cannot fall back to raw `git commit`
  or `gh pr create` — the table survives context compaction.
- **Acceptance verification** — the last step in every plan
  delegates to a structured verification skill that checks CI
  status, PR state, and working copy before declaring done.
- **Pause and resume** — walk away mid-session and come back
  later. Task state persists through context compaction, and
  deferred work is routed to PR bookmarks or project TODOs.

[`Dev10x:fanout`](skills/fanout/SKILL.md) extends this to
multiple issues in parallel — each issue gets the **full
playbook** (branch → implement → test → review → PR → CI →
merge), not a collapsed shortcut. Issues run in isolated
worktrees to avoid merge conflicts, with dependency ordering
so blocking work lands first.

The result: you point at a ticket, walk away, and come back to
a groomed branch with atomic commits, a Job Story PR, passing
CI, and a clean review — not a half-finished session that needs
another hour of hand-holding.

### Planning that spans milestones

Single-ticket features are straightforward. Multi-milestone
projects — the ones that span bounded contexts, require
migration sequencing, and involve three teams — are where AI
sessions usually produce shallow plans that miss dependencies.

[`Dev10x:project-scope`](skills/project-scope/SKILL.md) turns a
parent ticket or free-text description into a structured project
with milestones, blocking relationships, and tracker integration
(Linear, JIRA, or GitHub Issues). Each child ticket gets
acceptance criteria, story point estimates, and clear dependency
links so future sessions know what to build next.

[`Dev10x:ticket-scope`](skills/ticket-scope/SKILL.md) goes
deeper on individual tickets — technical research, architecture
design, component identification, and implementation strategy.
The output is a scoping document that replaces ad-hoc
implementation decisions with structured planning before code is
written.

[`Dev10x:ddd`](skills/ddd/SKILL.md) supports the earliest phase:
domain exploration via Event Storming workshops. When a feature
spans multiple bounded contexts and the right decomposition isn't
obvious, the skill guides structured discovery of domain events,
aggregates, and context boundaries — producing models that inform
how tickets are split and sequenced.

Together, these skills create a planning chain:

```
Domain exploration (ddd) → Project decomposition (project-scope)
→ Ticket scoping (ticket-scope) → Implementation (work-on)
```

Each step produces artifacts (models, tickets, scoping docs) that
persist across sessions, so the AI picks up context instead of
starting from scratch every time.

### A complete scope-to-merge pipeline

Every step produces a precise, artifact-quality message — readable
by the next agent in the chain or a human reviewer glancing at
their phone:

| Step | Skill | Output |
|------|-------|--------|
| Scope | [`Dev10x:ticket-scope`](skills/ticket-scope/SKILL.md) | Architecture research, ticket update |
| Branch | [`Dev10x:work-on`](skills/work-on/SKILL.md) | Named branch, gathered context |
| Commit | [`Dev10x:git-commit`](skills/git-commit/SKILL.md) | Atomic commits with benefit-focused titles |
| Groom | [`Dev10x:git-groom`](skills/git-groom/SKILL.md) | Clean history, no fixup commits |
| PR | [`Dev10x:gh-pr-create`](skills/gh-pr-create/SKILL.md) | Job Story description, ticket links |
| Monitor | [`Dev10x:gh-pr-monitor`](skills/gh-pr-monitor/SKILL.md) | Background CI + review watch |
| Respond | [`Dev10x:gh-pr-respond`](skills/gh-pr-respond/SKILL.md) | Batched review responses, minimal noise |
| Review | [`Dev10x:gh-pr-review`](skills/gh-pr-review/SKILL.md) | Domain-routed review across 5 agents |

No step produces wall-of-text. Each output is sized for a Slack
preview, a PR comment, or a task list glance.

### Learning loops that calibrate to you

Code review findings, commit conventions, and PR feedback flow
back into CLAUDE.md rules and session memory. The more you
course-correct, the less you need to.

After a few sessions, the AI produces commits, PR descriptions,
and code that look like *you* wrote them — because it learned your
preferences, not generic defaults.

## Supervise, don't babysit

The plugin is designed around batched attention windows:

1. **Scope** — point at a ticket, let the AI research and plan
2. **Walk away** — skills and hooks keep the pipeline moving
3. **Check in** — task list shows where the session stands
4. **Course-correct** — give 2 minutes of guidance, walk away again
5. **Ship** — come back to a groomed branch, clean PR, ready for
   review

When you pop in during a coffee break, you see a task list — not
a wall of terminal output. Each artifact (commit message, PR body,
review comment) is concise enough to evaluate in seconds.

## Skill families

| Family | Skills | What it automates |
|--------|--------|-------------------|
| **Git** | [`git-commit`](skills/git-commit/SKILL.md), [`git-commit-split`](skills/git-commit-split/SKILL.md), [`git-fixup`](skills/git-fixup/SKILL.md), [`git-groom`](skills/git-groom/SKILL.md), [`git-promote`](skills/git-promote/SKILL.md), [`git-worktree`](skills/git-worktree/SKILL.md), [`git`](skills/git/SKILL.md), [`git-alias-setup`](skills/git-alias-setup/SKILL.md), [`release-notes`](skills/release-notes/SKILL.md) | Atomic commits, clean history, workspace isolation, release notes |
| **PR** | [`gh-pr-create`](skills/gh-pr-create/SKILL.md), [`gh-pr-review`](skills/gh-pr-review/SKILL.md), [`gh-pr-respond`](skills/gh-pr-respond/SKILL.md), [`gh-pr-monitor`](skills/gh-pr-monitor/SKILL.md), [`gh-pr-triage`](skills/gh-pr-triage/SKILL.md), [`gh-pr-fixup`](skills/gh-pr-fixup/SKILL.md), [`gh-pr-request-review`](skills/gh-pr-request-review/SKILL.md), [`gh-pr-bookmark`](skills/gh-pr-bookmark/SKILL.md), [`gh-pr-doctor`](skills/gh-pr-doctor/SKILL.md), [`gh-pr-merge`](skills/gh-pr-merge/SKILL.md), [`gh-context`](skills/gh-context/SKILL.md), [`request-review`](skills/request-review/SKILL.md), [`review`](skills/review/SKILL.md), [`review-fix`](skills/review-fix/SKILL.md) | Full PR lifecycle, domain-routed review, self-review |
| **Tickets** | [`ticket-create`](skills/ticket-create/SKILL.md), [`ticket-branch`](skills/ticket-branch/SKILL.md), [`ticket-scope`](skills/ticket-scope/SKILL.md), [`ticket-jtbd`](skills/ticket-jtbd/SKILL.md), [`work-on`](skills/work-on/SKILL.md), [`linear`](skills/linear/SKILL.md), [`project-scope`](skills/project-scope/SKILL.md), [`investigate`](skills/investigate/SKILL.md) | Issue tracker integration, ticket scoping, bug investigation |
| **Park** | [`park`](skills/park/SKILL.md), [`park-todo`](skills/park-todo/SKILL.md), [`park-remind`](skills/park-remind/SKILL.md), [`park-discover`](skills/park-discover/SKILL.md) | Deferred work parking |
| **Scoping** | [`scope`](skills/scope/SKILL.md), [`jtbd`](skills/jtbd/SKILL.md), [`adr`](skills/adr/SKILL.md), [`adr-evaluate`](skills/adr-evaluate/SKILL.md), [`ddd`](skills/ddd/SKILL.md) | Architecture decisions, Job Story format, DDD workshops |
| **QA** | [`qa-scope`](skills/qa-scope/SKILL.md), [`qa-self`](skills/qa-self/SKILL.md), [`playwright`](skills/playwright/SKILL.md), [`py-test`](skills/py-test/SKILL.md) | Test planning, self-review, browser testing, pytest runner |
| **Session** | [`session-tasks`](skills/session-tasks/SKILL.md), [`session-wrap-up`](skills/session-wrap-up/SKILL.md), [`plan-sync`](skills/plan-sync/SKILL.md), [`fanout`](skills/fanout/SKILL.md), [`verify-acc-dod`](skills/verify-acc-dod/SKILL.md) | In-session work tracking, parallel execution, acceptance verification |
| **DB** | [`db`](skills/db/SKILL.md), [`db-psql`](skills/db-psql/SKILL.md) | Safe database query planning and execution |
| **Tooling** | [`py-uv`](skills/py-uv/SKILL.md), [`slack`](skills/slack/SKILL.md), [`slack-review-request`](skills/slack-review-request/SKILL.md), [`slack-setup`](skills/slack-setup/SKILL.md), [`ask`](skills/ask/SKILL.md) | Python packaging, Slack notifications, interactive prompts |
| **Meta** | [`skill-create`](skills/skill-create/SKILL.md), [`skill-audit`](skills/skill-audit/SKILL.md), [`skill-index`](skills/skill-index/SKILL.md), [`audit-report`](skills/audit-report/SKILL.md), [`playbook`](skills/playbook/SKILL.md), [`skill-reinforcement`](skills/skill-reinforcement/SKILL.md), [`onboarding`](skills/onboarding/SKILL.md) | Create, audit, discover, and learn skills |
| **Maintenance** | [`memory-maintenance`](skills/memory-maintenance/SKILL.md), [`plugin-maintenance`](skills/plugin-maintenance/SKILL.md), [`upgrade-cleanup`](skills/upgrade-cleanup/SKILL.md), [`playbook-maintenance`](skills/playbook-maintenance/SKILL.md), [`context-audit`](skills/context-audit/SKILL.md) | Memory, permission, playbook, and context hygiene |

All skills use the `Dev10x:` prefix — type `/Dev10x:git-commit` in the Claude
Code CLI to run it. Run `/Dev10x:skill-index` for the full reference.

## Installation

```bash
claude plugin marketplace add Dev10x-Guru/dev10x-claude
claude plugin install Dev10x@Dev10x-Guru
```

Run these in your shell, not inside a Claude Code session — the
in-session `/plugin` slash commands are unreliable for install.

[Full installation guide →](docs/installation.md) — prerequisites,
dependencies, manual clone, develop branch, and verification.

## Why Dev10x?

[Why Dev10x →](docs/why-dev10x.md) — who it's for, what problems
it solves, and how it compares to alternatives.

## Community

The [Dev10x community on Skool](https://www.skool.com/Dev10x-1892)
is where plugin users get assistance, request features, and share
workflows. If you already have access to this repository, you do not
need to join Skool — it is a support and discussion hub, not a
gatekeeper for repo access.

## Development

[Development guide →](docs/development.md)

## Star History

<a href="https://www.star-history.com/?repos=Dev10x-Guru%2Fdev10x-claude&type=date&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/image?repos=Dev10x-Guru/dev10x-claude&type=date&theme=dark&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/image?repos=Dev10x-Guru/dev10x-claude&type=date&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/image?repos=Dev10x-Guru/dev10x-claude&type=date&legend=bottom-right" />
 </picture>
</a>
