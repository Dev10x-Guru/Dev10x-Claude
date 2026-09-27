# Model Tier Reference

User-facing guide to model assignments across Dev10x agents
and skills. Use this to understand cost/quality tradeoffs
and configure per-project overrides.

## Tier Framework

Each task dispatched by Dev10x is assigned a tier that
determines which Claude model runs it:

| Tier | Default Model | Use Case |
|------|---------------|----------|
| **Monitor** | haiku | CI polling, status checks, log watching |
| **Gather** | haiku | Context fetching, API calls, data collection |
| **Replicate** | haiku/sonnet | Existing patterns, boilerplate, mechanical transforms |
| **Analyze** | sonnet | Pattern matching, triage, test validation |
| **Review** | sonnet | Code review, PR review, checklist-driven analysis |
| **Design** | opus | New components, architecture decisions, complex design |
| **Investigate** | opus | Root cause analysis, deep debugging, cross-system tracing |

Higher tiers produce better results but cost more tokens.

## Agent Model Assignments

### Named Agents (`agents/`)

| Agent | Model | Tier |
|-------|-------|------|
| `adr-reviewer` | sonnet | Analyze |
| `architect-api` | sonnet | Analyze |
| `architect-db` | sonnet | Analyze |
| `architect-domain` | sonnet | Analyze |
| `architect-frontend` | sonnet | Analyze |
| `architect-infra` | sonnet | Analyze |
| `architecture-advisor` | opus | Design |
| `code-reviewer` | opus | Review |
| `infrastructure-investigator` | sonnet | Analyze |
| `issue-investigator` | opus | Investigate |
| `permission-auditor` | sonnet | Analyze |
| `pytest-tester` | sonnet | Analyze |
| `pytest-test-writer` | sonnet | Analyze |
| `reviewer-celery` | sonnet | Review |
| `reviewer-e2e` | sonnet | Review |
| `reviewer-frontend` | sonnet | Review |
| `reviewer-graphql` | sonnet | Review |
| `reviewer-migration` | sonnet | Review |
| `reviewer-signals` | sonnet | Review |
| `reviewer-test-flaky` | sonnet | Review |
| `reviewer-test-patterns` | sonnet | Review |

### Skill Agent Dispatch

Skills that dispatch generic-purpose agents specify the model
explicitly per task tier:

| Skill | Phase | Model | Tier |
|-------|-------|-------|------|
| `dev10x:work-on` | Phase 2 (gather) | haiku | Gather |
| `dev10x:gh-pr-monitor` | CI polling | haiku | Monitor |
| `dev10x:gh-pr-monitor` | Long CI (>10 min) | sonnet | Analyze |
| `dev10x:skill-audit` | Wave 1+2 (5 phases) | sonnet | Analyze |
| `dev10x:adr-evaluate` | Architect advocates | opus | Design |

## Per-Project Model Overrides

Override model assignments in your project playbook without
modifying plugin files.

### Playbook Step Override

Add `model:` to any step in your playbook override file
(see `references/config-resolution.md` for paths):

```yaml
overrides:
  - play: feature
    steps:
      - subject: Code review
        type: detailed
        model: sonnet          # Override: use sonnet instead of opus
        skills: [dev10x:review, dev10x:review-fix]
```

When present, `model:` overrides the default model for agent
dispatch during that step. When absent, the skill's hardcoded
default applies.

### Fragment-Level Override

Fragments also support `model:` on individual steps:

```yaml
fragments:
  shipping-pipeline-budget:
    - subject: Code review
      type: detailed
      model: sonnet
      skills: [dev10x:review, dev10x:review-fix]
    - subject: Monitor CI
      type: detailed
      model: haiku
      skills: [dev10x:gh-pr-monitor]
```

### Override Resolution Order

1. Step-level `model:` in user override playbook (highest priority)
2. Step-level `model:` in default playbook
3. Skill's hardcoded model (in SKILL.md Agent dispatch)
4. Agent spec's `model:` frontmatter (for named agents)
5. Session default model (lowest priority)

### Cost Optimization Examples

**Budget-conscious project** (prefer cheaper models):
```yaml
fragments:
  budget-shipping:
    - subject: Code review
      type: detailed
      model: sonnet
      skills: [dev10x:review, dev10x:review-fix]
    - subject: Monitor CI
      type: detailed
      model: haiku
      skills: [dev10x:gh-pr-monitor]
```

**Quality-critical project** (prefer stronger models):
```yaml
overrides:
  - play: feature
    steps:
      - subject: Design implementation approach
        type: epic
        model: opus
```

## When to Override

Override model selection when:
- Token budget is constrained and you want cheaper tiers
- A specific step consistently produces poor results and
  needs a stronger model
- Your project has unusual complexity that warrants
  promoting a tier

Do not override when:
- The default works well (most common case)
- You are unsure which model to choose (defaults are tuned)
