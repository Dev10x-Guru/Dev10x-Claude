# Rules & Agents Architecture

Contributor reference for the multi-agent code review system.
This file is loaded on-demand, not every session.

## Architecture

The code review system uses a **multi-agent architecture**:

1. **Orchestrator** (`claude-code-review.yml`) — classifies changed
   files and dispatches to domain-specific agents
2. **Agent specs** (`.claude/agents/`) — focused checklists for each
   review domain
3. **Rules** (`.claude/rules/`) — always-loaded essentials and
   path-scoped rules
4. **References** (`references/`) — detailed guides loaded on-demand
   by skills and CI workflows

## Loading Strategy

| Location | When loaded | Content |
|----------|------------|---------|
| `.claude/rules/essentials.md` | Every session | Universal conventions |
| `.claude/rules/INDEX.md` | Every session | Agent routing table |
| `.claude/rules/skill-naming.md` | When editing `skills/**` | Skill naming conventions |
| `.claude/rules/agents.md` | When editing `agents/**` | Plugin-distributed agent specs |
| `.claude/rules/github-workflows.md` | When editing `.github/workflows/**` | GitHub Actions patterns |
| `references/*.md` | On-demand by skills/CI | Detailed git, review, JTBD guides |

## Reference Documents

| File | Topic | Loaded by |
|------|-------|-----------|
| `git-commits.md` | Commit format, gitmoji | `dev10x:git-commit` skill |
| `git-pr.md` | PR format, grooming | `dev10x:gh-pr-create` skill |
| `git-jtbd.md` | Job Story format | `dev10x:jtbd` skill |
| `review-guidelines.md` | Review workflow, threads | `dev10x:gh-pr-review` skill |
| `review-checks-common.md` | False positives, verification | Review agent specs |
| `eval-schema.md` | Evaluation assertions | `reviewer-skill.md` (item 19) |
| `skill-invocation.md` | Skill() syntax, delegation | `reviewer-skill.md` (items 8g, 9a) |
| `task-orchestration.md` | Orchestration patterns | All skills |

## Agent Specs (`.claude/agents/`)

Internal review-only agents (≤ 50 lines each).

| File | Trigger | References |
|------|---------|------------|
| `reviewer-generic.md` | `**/*.py`, `**/*.sh` | `references/review-checks-common.md` |
| `reviewer-infra.md` | `Makefile`, `**/*.sh`, `bin/**`, `.github/workflows/**` | `references/review-checks-common.md` |
| `reviewer-docs.md` | `docs/**`, `.claude/**/*.md`, `README.md` | `references/review-checks-common.md` |
| `reviewer-rules-maintenance.md` | `.claude/rules/**`, `.claude/agents/**`, `agents/**` | (self-contained) |
| `reviewer-skill.md` | `skills/**` | `.claude/rules/skill-naming.md`, `references/skill-invocation.md`, `references/eval-schema.md` |
| `reviewer-skill-behavior.md` | `skills/**` | `references/task-orchestration.md`, `.claude/rules/skill-gates.md` |

## Plugin-Distributed Sub-Agents (`agents/`)

Sub-agent specs shipped with the plugin for user workflows (≤ 200 lines).
Distinct from `.claude/agents/` — operational agents, not review checklists.

## Size Budgets

| File type | Max lines |
|-----------|-----------|
| Rule files | 200 |
| Agent specs | 50 |
| Reference docs | 200 |
| `CLAUDE.md` | 100 |

When a file reaches 80% of its budget, plan a split.

## Budget Overrides

Budgets are guidelines to prevent sprawl. Exceptions permitted when:

1. **Content is semantically cohesive** — splitting would obscure
   relationships
2. **All consumers link to a single file** — splits increase
   maintenance burden
3. **Author justification is explicit** — rationale documented in PR
4. **A split plan is conditional** — team commits to splitting if
   maintenance becomes problematic

Current overrides:
- `references/task-orchestration.md` (367 lines) — 7 orchestration
  patterns form a unified framework that 43+ skills reference atomically
- `.claude/agents/reviewer-skill.md` — split completed into
  `reviewer-skill.md` (structure/tools) and
  `reviewer-skill-behavior.md` (behavior/orchestration)

Reviewers must flag overrides with `[OVERRIDE DETECTED]` comments.
