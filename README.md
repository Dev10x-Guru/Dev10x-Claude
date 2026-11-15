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

When Claude uses `/dev10x-coding:gh-pr-create` instead of raw `gh` commands, every
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

[`dev10x-coding:work-on`](plugins/coding/skills/work-on/SKILL.md) solves this with a
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

[`dev10x-coding:fanout`](plugins/coding/skills/fanout/SKILL.md) extends this to
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

[`dev10x-scoping:project-scope`](plugins/scoping/skills/project-scope/SKILL.md) turns a
parent ticket or free-text description into a structured project
with milestones, blocking relationships, and tracker integration
(Linear, JIRA, or GitHub Issues). Each child ticket gets
acceptance criteria, estimates, and clear dependency links so
future sessions know what to build next.

[`dev10x-scoping:estimate`](plugins/scoping/skills/estimate/SKILL.md) is the one method
behind every estimate. It sizes implementation at agent pace and
counts the human gates that still decide the calendar: review,
review wait, testing and documentation. Effort and elapsed time
are reported separately.

[`dev10x-scoping:ticket-scope`](plugins/scoping/skills/ticket-scope/SKILL.md) goes
deeper on individual tickets — technical research, architecture
design, component identification, and implementation strategy.
The output is a scoping document that replaces ad-hoc
implementation decisions with structured planning before code is
written.

[`dev10x-scoping:ddd`](plugins/scoping/skills/ddd/SKILL.md) supports the earliest phase:
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
| Scope | [`dev10x-scoping:ticket-scope`](plugins/scoping/skills/ticket-scope/SKILL.md) | Architecture research, ticket update |
| Branch | [`dev10x-coding:work-on`](plugins/coding/skills/work-on/SKILL.md) | Named branch, gathered context |
| Commit | [`dev10x-coding:git-commit`](plugins/coding/skills/git-commit/SKILL.md) | Atomic commits with benefit-focused titles |
| Groom | [`dev10x-coding:git-groom`](plugins/coding/skills/git-groom/SKILL.md) | Clean history, no fixup commits |
| PR | [`dev10x-coding:gh-pr-create`](plugins/coding/skills/gh-pr-create/SKILL.md) | Job Story description, ticket links |
| Monitor | [`dev10x-coding:gh-pr-monitor`](plugins/coding/skills/gh-pr-monitor/SKILL.md) | Background CI + review watch |
| Respond | [`dev10x-coding:gh-pr-respond`](plugins/coding/skills/gh-pr-respond/SKILL.md) | Batched review responses, minimal noise |
| Review | [`dev10x-coding:gh-pr-review`](plugins/coding/skills/gh-pr-review/SKILL.md) | Domain-routed review across 5 agents |

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
| **Git** | [`git-commit`](plugins/coding/skills/git-commit/SKILL.md), [`git-commit-split`](plugins/coding/skills/git-commit-split/SKILL.md), [`git-fixup`](plugins/coding/skills/git-fixup/SKILL.md), [`git-groom`](plugins/coding/skills/git-groom/SKILL.md), [`git-promote`](plugins/coding/skills/git-promote/SKILL.md), [`git-worktree`](plugins/coding/skills/git-worktree/SKILL.md), [`git`](plugins/coding/skills/git/SKILL.md), [`git-alias-setup`](plugins/coding/skills/git-alias-setup/SKILL.md), [`release-notes`](plugins/coding/skills/release-notes/SKILL.md) | Atomic commits, clean history, workspace isolation, release notes |
| **PR** | [`gh-pr-create`](plugins/coding/skills/gh-pr-create/SKILL.md), [`gh-pr-review`](plugins/coding/skills/gh-pr-review/SKILL.md), [`gh-pr-respond`](plugins/coding/skills/gh-pr-respond/SKILL.md), [`gh-pr-monitor`](plugins/coding/skills/gh-pr-monitor/SKILL.md), [`gh-pr-triage`](plugins/coding/skills/gh-pr-triage/SKILL.md), [`gh-pr-fixup`](plugins/coding/skills/gh-pr-fixup/SKILL.md), [`gh-pr-request-review`](plugins/coding/skills/gh-pr-request-review/SKILL.md), [`gh-pr-bookmark`](plugins/coding/skills/gh-pr-bookmark/SKILL.md), [`gh-pr-doctor`](plugins/coding/skills/gh-pr-doctor/SKILL.md), [`gh-pr-merge`](plugins/coding/skills/gh-pr-merge/SKILL.md), [`gh-context`](skills/gh-context/SKILL.md), [`request-review`](plugins/coding/skills/request-review/SKILL.md), [`review`](plugins/coding/skills/review/SKILL.md), [`review-fix`](plugins/coding/skills/review-fix/SKILL.md), [`review-pack`](plugins/qa/skills/review-pack/SKILL.md) (`dev10x-qa`) | Full PR lifecycle, domain-routed review, self-review, reviewer-facing evidence packs |
| **Tickets** | [`ticket-branch`](plugins/coding/skills/ticket-branch/SKILL.md), [`work-on`](plugins/coding/skills/work-on/SKILL.md), [`investigate`](plugins/coding/skills/investigate/SKILL.md); in the `dev10x-scoping` plugin: [`ticket-create`](plugins/scoping/skills/ticket-create/SKILL.md), [`ticket-scope`](plugins/scoping/skills/ticket-scope/SKILL.md), [`ticket-jtbd`](plugins/scoping/skills/ticket-jtbd/SKILL.md), [`linear`](plugins/scoping/skills/linear/SKILL.md), [`jira`](plugins/scoping/skills/jira/SKILL.md), [`project-scope`](plugins/scoping/skills/project-scope/SKILL.md), [`project-audit`](plugins/scoping/skills/project-audit/SKILL.md), [`spec-sync`](plugins/scoping/skills/spec-sync/SKILL.md), [`spec-update`](plugins/scoping/skills/spec-update/SKILL.md) | Issue tracker integration, ticket scoping, bug investigation, spec-first changes |
| **Park** | in the `dev10x-tasks` plugin: [`park`](plugins/tasks/skills/park/SKILL.md), [`park-todo`](plugins/tasks/skills/park-todo/SKILL.md), [`park-remind`](plugins/tasks/skills/park-remind/SKILL.md), [`park-discover`](plugins/tasks/skills/park-discover/SKILL.md) | Deferred work parking |
| **Scoping** | in the `dev10x-scoping` plugin: [`scope`](plugins/scoping/skills/scope/SKILL.md), [`estimate`](plugins/scoping/skills/estimate/SKILL.md), [`jtbd`](plugins/scoping/skills/jtbd/SKILL.md), [`adr`](plugins/scoping/skills/adr/SKILL.md), [`adr-evaluate`](plugins/scoping/skills/adr-evaluate/SKILL.md), [`ddd`](plugins/scoping/skills/ddd/SKILL.md), [`diagram-sequence`](plugins/scoping/skills/diagram-sequence/SKILL.md), [`diagram-c4`](plugins/scoping/skills/diagram-c4/SKILL.md), [`diagram-bpmn`](plugins/scoping/skills/diagram-bpmn/SKILL.md), [`artifact`](plugins/scoping/skills/artifact/SKILL.md) | Architecture decisions, Job Story format, DDD workshops, diagrams, shareable report pages |
| **QA** | [`qa-scope`](plugins/coding/skills/qa-scope/SKILL.md), [`py-test`](plugins/coding/skills/py-test/SKILL.md); in the `dev10x-qa` plugin: [`qa-self`](plugins/qa/skills/qa-self/SKILL.md), [`playwright`](plugins/qa/skills/playwright/SKILL.md), [`qa-publish`](plugins/qa/skills/qa-publish/SKILL.md), [`tts`](plugins/qa/skills/tts/SKILL.md), [`yt-upload`](plugins/qa/skills/yt-upload/SKILL.md) | Test planning, self-review, browser testing, narrated walkthroughs, pytest runner |
| **Session** | [`fanout`](plugins/coding/skills/fanout/SKILL.md), [`verify-acc-dod`](plugins/coding/skills/verify-acc-dod/SKILL.md); in the `dev10x-tasks` plugin: [`session-tasks`](plugins/tasks/skills/session-tasks/SKILL.md), [`session-wrap-up`](plugins/tasks/skills/session-wrap-up/SKILL.md), [`plan-sync`](plugins/tasks/skills/plan-sync/SKILL.md), [`reflect`](plugins/tasks/skills/reflect/SKILL.md) | In-session work tracking, parallel execution, acceptance verification, lessons into a vault |
| **DB** | [`db`](plugins/db/skills/db/SKILL.md), [`db-psql`](plugins/db/skills/db-psql/SKILL.md), [`sql-handoff`](plugins/db/skills/sql-handoff/SKILL.md) | Safe database query planning, execution, and hand-run write handoff |
| **Tooling** | [`py-uv`](plugins/coding/skills/py-uv/SKILL.md), [`slack-review-request`](plugins/coding/skills/slack-review-request/SKILL.md), [`ask`](skills/ask/SKILL.md); in the `dev10x-comm` plugin: [`slack`](plugins/comm/skills/slack/SKILL.md), [`slack-setup`](plugins/comm/skills/slack-setup/SKILL.md), [`gchat`](plugins/comm/skills/gchat/SKILL.md), [`gog`](plugins/comm/skills/gog/SKILL.md), [`bus`](plugins/comm/skills/bus/SKILL.md), [`overwatch`](plugins/comm/skills/overwatch/SKILL.md), [`voice-channel`](plugins/comm/skills/voice-channel/SKILL.md) | Python packaging, Slack and Google Chat notifications, session messaging, interactive prompts |
| **Meta** | [`playbook`](skills/playbook/SKILL.md), [`diag-friction`](skills/diag-friction/SKILL.md), [`onboarding`](skills/onboarding/SKILL.md); in the `dev10x-teach` plugin: [`skill-create`](plugins/teach/skills/skill-create/SKILL.md), [`skill-audit`](plugins/teach/skills/skill-audit/SKILL.md), [`skill-audit-queue`](plugins/teach/skills/skill-audit-queue/SKILL.md), [`skill-index`](plugins/teach/skills/skill-index/SKILL.md), [`audit-file`](plugins/teach/skills/audit-file/SKILL.md) | Create, audit, discover, and learn skills |
| **Maintenance** | [`plugin-maintenance`](skills/plugin-maintenance/SKILL.md), [`upgrade-cleanup`](skills/upgrade-cleanup/SKILL.md), [`playbook-maintenance`](skills/playbook-maintenance/SKILL.md), [`permission-audit-apply`](skills/permission-audit-apply/SKILL.md), [`skill-prune`](skills/skill-prune/SKILL.md); in the `dev10x-teach` plugin: [`memory-maintenance`](plugins/teach/skills/memory-maintenance/SKILL.md), [`context-audit`](plugins/teach/skills/context-audit/SKILL.md) | Memory, permission, playbook, and context hygiene; applying audit fixes and hiding irrelevant skills |

Every link under `plugins/coding/` is a skill of the `dev10x-coding`
plugin. Core skills use the `dev10x:` prefix — type `/dev10x:onboarding`
in the Claude Code CLI to run it; a satellite plugin's skills use its own
prefix, such as `/dev10x-coding:git-commit` or `dev10x-teach:`. Run
`/dev10x-teach:skill-index` for the full reference.

## Installation

```bash
claude plugin marketplace add Dev10x-Guru/dev10x-claude
claude plugin install dev10x@Dev10x-Guru
claude plugin install dev10x-qa@Dev10x-Guru   # optional: self-QA walkthroughs
claude plugin install dev10x-infra@Dev10x-Guru   # optional: AWS secrets, k8s
claude plugin install dev10x-db@Dev10x-Guru      # optional: read-only SQL
claude plugin install dev10x-comm@Dev10x-Guru    # optional: Slack, Chat, bus
claude plugin install dev10x-teach@Dev10x-Guru   # optional: skill authoring, audits, index
claude plugin install dev10x-tasks@Dev10x-Guru   # optional: park, wrap-up, reflect
claude plugin install dev10x-scoping@Dev10x-Guru # optional: tickets, scoping, ADRs, diagrams
claude plugin install dev10x-coding@Dev10x-Guru  # commits, PRs, review, work-on (needs dev10x-tasks)
```

Run these in your shell, not inside a Claude Code session — the
in-session `/plugin` slash commands are unreliable for install.

[Full installation guide →](docs/installation.md) — prerequisites,
dependencies, manual clone, develop branch, and verification.

### MCP tools only — Claude Desktop and other MCPB hosts

Starting with v0.109.0, every
[release](https://github.com/Dev10x-Guru/dev10x-claude/releases)
attaches `dev10x-<version>.mcpb`, an [MCP Bundle](https://github.com/modelcontextprotocol/mcpb)
of the `cli` MCP server (PR lifecycle, issues, git history, CI
monitoring, gate policy). Download it and open it in Claude Desktop —
or any MCPB-aware host — to install the tools in one click, without
the Claude Code plugin.

The bundle needs [`uv`](https://docs.astral.sh/uv/) on `PATH`, plus
`git` and an authenticated `gh` for the GitHub tools. Skills, hooks
and the `db` server are not in it: skills and hooks are Claude Code
plugin features, and `db` reads local `databases.yaml` and keyring
credentials that a bundle cannot carry.

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
