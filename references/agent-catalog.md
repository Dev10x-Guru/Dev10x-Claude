# Agent Catalog

Every agent spec in this repo, by where it lives and what triggers it.
Moved out of `.claude/rules/INDEX.md`, which loads in every session,
to keep that index inside its 200-line rule budget (GH-1750). The
routing that decides which reviewer sees a file stays in INDEX.md
§ File Patterns -> Agents -> References; this file is the catalog.

## Agent Specs (`.claude/agents/`)

Internal review-only agents (≤ 50 lines each).

| File | Trigger | References |
|------|---------|------------|
| `reviewer-generic.md` | `**/*.py`, `**/*.sh` | `references/review-checks-common.md` |
| `reviewer-infra.md` | `Makefile`, `**/*.sh`, `bin/**`, `hooks/**`, `.github/**` | `references/review-checks-common.md` |
| `reviewer-docs.md` | `docs/**`, `.claude/**/*.md`, `CLAUDE.md`, `README.md` | `references/review-checks-common.md` |
| `reviewer-rules-maintenance.md` | `.claude/rules/**`, `.claude/agents/**`, `agents/**`, `references/**` | (self-contained) |
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
| `spec-reviewer.md` | Verify diff matches ticket AC (Phase 0 of review) |

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
| `reviewer-e2e.md` | `**/features/**/*.feature`, `**/features/steps/*.py`, `**/environment.py`, `**/e2e/**/*.py` |
| `reviewer-frontend.md` | `**/*.svelte`, `**/*.astro`, `**/*.tsx` |
| `reviewer-graphql.md` | `**/api/queries.py`, `**/api/mutations.py`, `**/schema.py` |
| `reviewer-migration.md` | `**/migrations/*.py` |
| `reviewer-signals.md` | `**/signals.py`, `**/handlers.py` |
| `reviewer-test-flaky.md` | `**/tests/**/*.py` (flaky risks) |
| `reviewer-test-patterns.md` | `**/tests/**/*.py` (patterns) |
