# Rule Index & Agent Routing

Path-aware routing table and directory documentation for `.claude/rules/`.

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

## Directory Contract

- This file is the single source of truth in `.claude/rules/`.
- Full rule content lives in `references/*.md`.
- Agent triggers and checklists live in `.claude/agents/*.md`.
- Path-scoped rules (e.g., `skill-naming.md`) load conditionally.

## File Patterns -> Agents -> References

| File Pattern | Primary Agent | Required References |
|---|---|---|
| `**/*.py`, `**/*.sh` | `reviewer-generic`, `reviewer-security`, `reviewer-silent-failures` | `references/review-checks-common.md` |
| `Makefile`, `bin/**`, `hooks/**`, `*.sh` | `reviewer-infra` | `references/review-checks-common.md` |
| `docs/**`, `.claude/**/*.md`, `README.md` | `reviewer-docs` | `references/review-checks-common.md` |
| `.claude/rules/**`, `.claude/agents/**`, `agents/**` | `reviewer-rules-maintenance` | (self-contained) |
| `skills/**` | `reviewer-skill`, `reviewer-skill-behavior` | `.claude/rules/skill-naming.md`, `references/skill-invocation.md`, `references/eval-schema.md` |
| `**/tasks.py`, `**/celery.py` | `reviewer-celery` | (self-contained) |
| `**/e2e/**/*.py`, `**/e2e/**/*.feature` | `reviewer-e2e` | (self-contained) |
| `**/*.svelte`, `**/*.astro`, `**/*.tsx` | `reviewer-frontend` | (self-contained) |
| `**/api/queries.py`, `**/api/mutations.py` | `reviewer-graphql` | (self-contained) |
| `**/migrations/*.py` | `reviewer-migration` | (self-contained) |
| `**/signals.py`, `**/handlers.py` | `reviewer-signals` | (self-contained) |
| `**/tests/**/*.py` | `reviewer-test-flaky`, `reviewer-test-patterns` | (self-contained) |

## Loading Strategy

| Location | When loaded | Content |
|----------|------------|---------|
| `.claude/rules/essentials.md` | Every session | Universal conventions (~36 lines) |
| `.claude/rules/skill-naming.md` | When editing `skills/**` | Skill naming conventions |
| `.claude/rules/agents.md` | When editing `agents/**` | Plugin-distributed agent specs |
| `.claude/rules/model-selection.md` | When editing `agents/**` or `skills/**` | Model & effort selection for agent dispatch |
| `.claude/rules/playbook-pattern.md` | When editing `skills/**` with playbooks | Playbook patterns, user customization, reviewer expectations |
| `.claude/rules/github-workflows.md` | When editing `.github/workflows/**` | GitHub Actions patterns |
| `.claude/rules/hook-state-schema.md` | When editing `hooks/**` state writers | Hook JSON state documentation |
| `.claude/rules/hook-patterns.md` | When editing `hooks/**` with dual implementations | Python-shell hook equivalence |
| `.claude/rules/performance.md` | Reference: post-dependency change monitoring | CLI startup baseline, profiling instructions |
| `.claude/rules/skill-body-extraction.md` | When editing `skills/**` | SKILL.md body extraction pattern, token reduction |
| `references/*.md` | On-demand by skills/CI | Detailed git, review, JTBD guides |

## Loading Order

1. Always load `CLAUDE.md`, `essentials.md`, and this `INDEX.md`.
2. Match changed files to agent(s) above.
3. Load only required references for matched agents.
4. Path-scoped rules (`skill-naming.md`, `agents.md`,
   `github-workflows.md`) load per their scope annotations.

## Cross-Cutting Checks

Always apply `references/review-checks-common.md`.

## Reference Documents (`references/`)

| File | Topic | Loaded by | Scope |
|------|-------|-----------|-------|
| `git-commits.md` | Commit format, gitmoji, atomic commits | `Dev10x:git-commit` skill, PR hygiene CI | Mandatory for all commits |
| `git-pr.md` | PR format, grooming, review feedback | `Dev10x:gh-pr-create` skill, PR hygiene CI | Mandatory for all PRs |
| `git-jtbd.md` | Job Story format, principles, examples | `Dev10x:jtbd` skill, PR hygiene CI | Mandatory for JTBD decisions |
| `review-guidelines.md` | Review workflow, threads, summaries | `Dev10x:gh-pr-review` skill, code review CI | Mandatory for PR reviews |
| `review-checks-common.md` | False positives, verification | Review agent specs, code review CI | Mandatory for code review agents |
| `eval-schema.md` | Evaluation assertions format for skills | `reviewer-skill.md` (item 19) | Decision gate validation |
| `skill-invocation.md` | Skill() syntax, named parameters, delegation | `reviewer-skill.md` (items 8g, 9a) | Mandatory for skill reviews |
| `task-orchestration.md` | Orchestration patterns, auto-advance, batched decisions | All skills (via `## Orchestration` section) | Referenced, not auto-loaded |
| `code-sharing-patterns.md` | MCP imports, PEP 723 inlining, cross-context code | Review agents (false positive prevention) | Referenced, not auto-loaded |
| `permission-architecture.md` | Permission → hook execution order, hook-enabled rules | `permission-auditor` agent, `plugin-maintenance` skill (and the `upgrade-cleanup` entry point) | Referenced, not auto-loaded |
| `execution-modes.md` | Structural modes, per-step mode mappings, mode precedence | `work-on` skill, `playbook` skill | Referenced, not auto-loaded |
| `friction-levels.md` | Friction levels, gate behavior, playbook integration | `work-on` skill, `verify-acc-dod` skill | Referenced, not auto-loaded |
| `model-tiers.md` | Model assignments, tier framework, per-project overrides | `model-selection.md` rule, playbook system | Referenced, not auto-loaded |
| `skill-pipelines.md` | Skill composition pipelines, standalone invocation | `Dev10x:work-on` skill, pipeline documentation | Referenced, not auto-loaded |
| `config-resolution.md` | 3-tier config paths, project mapping format | All playbook/settings skills | Referenced, not auto-loaded |

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
| `reviewer-security.md` | `**/*.py`, `**/*.sh` | (self-contained) |
| `reviewer-silent-failures.md` | `**/*.py` | (self-contained) |

## Plugin-Distributed Agents (`agents/`)

Agents shipped with the plugin for all users (≤ 200 lines each).
These cover operational workflows, code review, architecture
evaluation, and testing — usable on any project.

### Operational Agents

| File | Purpose |
|------|---------|
| `permission-auditor.md` | Audit Claude Code permission settings |
| `architecture-advisor.md` | Evaluate architecture, identify design issues |
| `issue-investigator.md` | Deep-dive bug/error investigation |
| `infrastructure-investigator.md` | K8s/cloud infrastructure investigation |
| `code-reviewer.md` | Review branch changes against standards |
| `pytest-tester.md` | Run tests and verify coverage |
| `pytest-test-writer.md` | Write/review pytest tests |

### Architecture Evaluation Agents (for ADRs)

| File | Purpose |
|------|---------|
| `architect-api.md` | API design evaluation |
| `architect-db.md` | Database architecture evaluation |
| `architect-domain.md` | Domain modeling evaluation |
| `architect-frontend.md` | Frontend architecture evaluation |
| `architect-infra.md` | Infrastructure evaluation |
| `adr-reviewer.md` | ADR synthesis and fact-checking |

### Domain Review Agents

| File | Trigger |
|------|---------|
| `reviewer-celery.md` | `**/tasks.py`, `**/celery.py` |
| `reviewer-e2e.md` | `**/e2e/**/*.py`, `**/e2e/**/*.feature` |
| `reviewer-frontend.md` | `**/*.svelte`, `**/*.astro`, `**/*.tsx` |
| `reviewer-graphql.md` | `**/api/queries.py`, `**/schema.py` |
| `reviewer-migration.md` | `**/migrations/*.py` |
| `reviewer-signals.md` | `**/signals.py`, `**/handlers.py` |
| `reviewer-test-flaky.md` | `**/tests/**/*.py` (flaky risks) |
| `reviewer-test-patterns.md` | `**/tests/**/*.py` (patterns) |

## Size Budgets

| File type | Max lines |
|-----------|-----------|
| Rule files | 200 |
| Agent specs | 50 |
| Reference docs | 200 |
| `CLAUDE.md` | 100 |
| `SKILL.md` | 200 |

When a file reaches 80% of its budget, plan a split.

**SKILL.md overflow strategy**: extract stable content to
`skills/<name>/references/` (detailed schemas, full examples,
CI failure tables) or `skills/<name>/tool-calls/` (AskUserQuestion
call specs). Keep SKILL.md focused on: frontmatter, overview,
orchestration steps, decision gates.

**Known SKILL.md overrides** (orchestration hubs — semantically
cohesive, justified by scope):
- `work-on` (1191 lines) — 4-phase adaptive orchestrator with
  5 complete play definitions and subagent dispatch patterns
- `skill-audit` (1042 lines) — multi-wave audit with per-skill
  behavioral analysis patterns
- `fanout` (434 lines) — parallel work stream orchestrator with
  6-phase execution model and parallel group management

## Budget Overrides

File size budgets are guidelines to prevent sprawl. Exceptions are
permitted when:

1. **Content is semantically cohesive** — splitting would obscure
   relationships between concepts
2. **All consumers link to a single file** — multi-file splits would
   increase maintenance burden
3. **Author justification is explicit** — the rationale for keeping
   the file together is documented in the PR
4. **A split plan is conditional** — if maintenance becomes
   problematic, the team commits to splitting by [topic/pattern group]

Examples:
- `references/task-orchestration.md` (367 lines) exceeds the 200-line
  budget because 7 orchestration patterns form a unified framework that
  43+ skills reference atomically.
- `.claude/agents/reviewer-skill.md` was split into two files at 187
  lines: `reviewer-skill.md` (items 1-13, structure/tools) and
  `reviewer-skill-behavior.md` (items 14-20, behavior/orchestration).

Reviewers must flag overrides with `[OVERRIDE DETECTED]` comments and
verify:
- Cohesion justification is clear
- A conditional split plan exists
- The author acknowledges the override explicitly
