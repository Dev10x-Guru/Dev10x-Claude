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
| `Makefile`, `bin/**`, `hooks/**`, `*.sh`, `.github/**` | `reviewer-infra` | `references/review-checks-common.md` |
| `docs/**`, `.claude/**/*.md`, `CLAUDE.md`, `README.md` | `reviewer-docs` | `references/review-checks-common.md` |
| `.claude/rules/**`, `.claude/agents/**`, `agents/**`, `references/**` | `reviewer-rules-maintenance` | (self-contained) |
| `skills/**` | `reviewer-skill`, `reviewer-skill-behavior` | `.claude/rules/skill-naming.md`, `references/skill-invocation.md`, `references/eval-schema.md` |
| `**/tasks.py`, `**/celery.py` | `reviewer-celery` | (self-contained) |
| `**/features/**/*.feature`, `**/features/steps/*.py`, `**/environment.py`, `**/e2e/**/*.py` | `reviewer-e2e` | (self-contained) |
| `**/*.svelte`, `**/*.astro`, `**/*.tsx` | `reviewer-frontend` | (self-contained) |
| `**/api/queries.py`, `**/api/mutations.py` | `reviewer-graphql` | (self-contained) |
| `**/migrations/*.py` | `reviewer-migration` | (self-contained) |
| `**/signals.py`, `**/handlers.py` | `reviewer-signals` | (self-contained) |
| `**/tests/**/*.py` | `reviewer-test-flaky`, `reviewer-test-patterns` | (self-contained) |

## Loading Strategy

| Location | When loaded | Content |
|----------|------------|---------|
| `.claude/rules/essentials.md` | Every session | Universal conventions (line count drifts — see the file, not this table; GH-1438) |
| `.claude/rules/skill-naming.md` | When editing `skills/**` | Skill naming conventions |
| `.claude/rules/agents.md` | When editing `agents/**` | Plugin-distributed agent specs |
| `.claude/rules/model-selection.md` | When editing `agents/**` or `skills/**` | Model & effort selection for agent dispatch |
| `.claude/rules/playbook-pattern.md` | When editing `skills/**` with playbooks | Playbook patterns, user customization, reviewer expectations |
| `.claude/rules/github-workflows.md` | When editing `.github/workflows/**` | GitHub Actions patterns |
| `.claude/rules/claude-ci-cost.md` | When editing `.github/workflows/claude*.yml`, `.github/claude/**`, `.github/claude-ci-settings.json`, `.github/scripts/claude-pr-context/**` | Prompt-caching prefix, prefetch, usage reporting (GH-1585), CLI pin (GH-1615), federation (GH-1622) |
| `.claude/rules/hook-state-schema.md` | When editing `hooks/**` state writers | Hook JSON state documentation |
| `.claude/rules/hook-dispatch-patterns.md` | When editing `hooks/**`, `src/dev10x/hooks/**`, `src/dev10x/*/hooks/**`, `tests/hooks/**` | Python-shell hook equivalence, orchestrator dispatch, Stop verdicts, PostToolUse formatter scope (GH-1867) |
| `.claude/rules/hook-validator-profiles.md` | When editing `hooks/scripts/validate-*.py`, `src/dev10x/core/hooks/hook_transport.py`, `src/dev10x/core/validators/**`, `src/dev10x/validators/**`, `tests/hooks/test_hook_transport.py`, `tests/validators/**` | Profile tiers, DX rule IDs, per-rule design notes, hook output streams (GH-1867) |
| `.claude/rules/hook-input-patterns.md` | When editing `hooks/**`, `src/dev10x/hooks/**`, `src/dev10x/*/hooks/**`, `src/dev10x/core/validators/**` | Safe parsing of hook tool input (JSON, commands) |
| `.claude/rules/cwd-discipline.md` | When editing `src/dev10x/**` Python that runs subprocesses or reads CWD | GH-979 effective-CWD routing, no module-scope GitContext |
| `.claude/rules/uv-script-dependency-pins.md` | When adding/editing a PEP 723 uv-script's `# dependencies = [...]` or `pyproject.toml` dependency arrays | GH-916 upper-bound requirement, `requires-python` exception, detector + pre-commit wiring |
| `.claude/rules/script-domain-boundaries.md` | When editing `skills/**/scripts/**` or `src/dev10x/**/{skills,domain,mcp}/**` — the domain functions and MCP handlers it binds (GH-1763) | print-vs-logging + sys.exit-vs-Result conventions (GH-246 H3/H7) |
| `.claude/rules/performance.md` | Reference: post-dependency change monitoring | CLI startup baseline, profiling instructions |
| `.claude/rules/skill-body-extraction.md` | When editing `skills/**` | SKILL.md body extraction pattern, token reduction |
| `.claude/rules/agent-body-extraction.md` | When editing `agents/**` | Agent spec body extraction pattern, token reduction |
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
| `git-commits.md` | Commit format, gitmoji, atomic commits | `dev10x:git-commit` skill, PR hygiene CI | Mandatory for all commits |
| `git-pr.md` | PR format, grooming, review feedback | `dev10x:gh-pr-create` skill, PR hygiene CI | Mandatory for all PRs |
| `git-jtbd.md` | Job Story format, principles, examples | `dev10x:jtbd` skill, PR hygiene CI | Mandatory for JTBD decisions |
| `review-guidelines.md` | Review workflow, threads, summaries | `dev10x:gh-pr-review` skill, code review CI | Mandatory for PR reviews |
| `review-checks-common.md` | False positives, verification | Review agent specs, code review CI | Mandatory for code review agents |
| `review-routing.md` | One subagent per reviewer spec: routing, dispatch, merge (GH-1741) | Code review CI Step 3, `dev10x:review` Step 4 | Mandatory for both review orchestrators |
| `eval-schema.md` | Evaluation assertions format for skills | `reviewer-skill.md` (item 19) | Decision gate validation |
| `skill-invocation.md` | Skill() syntax, named parameters, delegation | `reviewer-skill.md` (items 8g, 9a) | Mandatory for skill reviews |
| `task-orchestration.md` | Orchestration patterns, auto-advance, batched decisions | All skills (via `## Orchestration` section) | Referenced, not auto-loaded |
| `code-sharing-patterns.md` | MCP imports, PEP 723 inlining, cross-context code | Review agents (false positive prevention) | Referenced, not auto-loaded |
| `permission-architecture.md` | Permission → hook execution order, hook-enabled rules | `permission-auditor` agent, `plugin-maintenance` skill (and the `upgrade-cleanup` entry point) | Referenced, not auto-loaded |
| `permission-friction-taxonomy.md` | Friction types A–G, friction class map A–O, diagnosis D0–D5 | `permission-auditor` agent, `permission-investigator` skill, issue triage | Referenced, not auto-loaded |
| `execution-modes.md` | Structural modes, per-step mode mappings, mode precedence | `work-on` skill, `playbook` skill | Referenced, not auto-loaded |
| `friction-levels.md` | Friction levels, gate behavior, playbook integration | `work-on` skill, `verify-acc-dod` skill | Referenced, not auto-loaded |
| `model-tiers.md` | Model assignments, tier framework, per-project overrides | `model-selection.md` rule, playbook system | Referenced, not auto-loaded |
| `skill-pipelines.md` | Skill composition pipelines, standalone invocation | `dev10x:work-on` skill, pipeline documentation | Referenced, not auto-loaded |
| `config-resolution.md` | 3-tier config paths, project mapping format | All playbook/settings skills | Referenced, not auto-loaded |
| `config-files.md` | Per-file tiers, paths and formats of every Dev10x config file (GH-1785) | All playbook/settings skills | Referenced, not auto-loaded |
| `testing-patterns.md` | Pytest fixture composition, async handlers, parametrized tests | Code reviews, test authoring | Referenced, not auto-loaded |
| `review-readiness.md` | Readiness check before a review request; SENT-NOT-READY / WENT-RED-AFTER audit (GH-1834) | `dev10x:request-review`, `dev10x:gh-pr-request-review`, `dev10x:foreman` | Referenced, not auto-loaded |
| `pr-backlog-deferral.md` | Deferring non-blocking review findings to a backlog | `dev10x:gh-pr-review` skill, code review CI | Referenced, not auto-loaded |
| `milestone-naming.md` | Milestone naming convention, initiative prefixes, `Depends on:` ordering (no sequence numbers) | `dev10x:project-scope`, `dev10x:work-on` milestone steps | Referenced, not auto-loaded |
| `backpressure.md` | Two-direction backpressure architecture (action gating + friction tuning + output gates) | Review & architecture docs, code review CI | Referenced, not auto-loaded |
| `mcp-tools/*.md` | Per-tool behavioural caveats and the version table, moved out of the always-loaded `mcp-tools.md` rule (GH-1606) | Callers of the tool each file names | Referenced, not auto-loaded |
| `html-artifact-reporting.md` | Optional HTML artifacts for long comparison-shaped reports; markdown stays default | `dev10x:ddd` deliverables, foreman morning report | Referenced, not auto-loaded |
| `diagrams/rendering.md` | Shared diagram render toolchain contract and failure table | `dev10x:diagram-sequence`, `dev10x:diagram-c4`, `dev10x:diagram-bpmn`, `dev10x:scope`, `dev10x:adr` | Referenced, not auto-loaded |
| `agent-catalog.md` | Every agent spec — internal reviewers in `.claude/agents/`, plugin-distributed agents in `agents/` — with its trigger (GH-1750) | Adding or auditing an agent spec | Referenced, not auto-loaded |
| `skill-personas.md` | Optional per-skill `persona:` field, its mirrored `**Persona:**` body line, and the pilot set (GH-1638) | `dev10x:skill-create`; the pilot skills `dev10x:review`, `dev10x:adr`, `dev10x:ticket-scope` | Referenced, not auto-loaded |
| `skill-size-overrides.md` | SKILL.md / `instructions.md` files allowed past the 200-line budget, with each justification (GH-1750) | Reviewing a skill over budget | Referenced, not auto-loaded |

## Agent Specs

Internal review-only agents live in `.claude/agents/` (≤ 50 lines
each); agents shipped to every user live in `agents/` (≤ 200 lines
each). The routing table above decides which reviewer sees a file;
the full catalog of both directories is
[`references/agent-catalog.md`](../../references/agent-catalog.md).

## Size Budgets

| File type | Max lines |
|-----------|-----------|
| Rule files | 200 |
| Agent specs | 50 |
| Reference docs | 200 |
| `CLAUDE.md` | 100 |
| `SKILL.md` | 200 |

When a file reaches 80% of its budget, plan a split. This index is a
rule file and holds itself to the same 200 lines: catalogs and
override lists go to `references/`, not here (GH-1750).

**SKILL.md overflow strategy**: extract stable content to
`skills/<name>/references/` (detailed schemas, full examples,
CI failure tables) or `skills/<name>/tool-calls/` (AskUserQuestion
call specs). Keep SKILL.md focused on: frontmatter, overview,
orchestration steps, decision gates.

**Known SKILL.md overrides** — the orchestration hubs allowed past
the budget (`work-on`, `skill-audit`, `fanout`, `foreman`,
`git-groom`, `plugin-maintenance`, `diag-friction`, `project-scope`,
`ticket-create`, `review`, `ddd`) and the justification for each are in
[`references/skill-size-overrides.md`](../../references/skill-size-overrides.md).
Record a new override there.

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
