# Backpressure Architecture

Dev10x applies backpressure in **two directions**, plus a tunable
enforcement layer. This document names the model, maps each surface to
its backpressure role, and links the detailed rule docs.

Background: [Backpressure Is All You Need](https://www.lucasfcosta.com/blog/backpressure-is-all-you-need)
(GH-430 audit). The article names 7 output-side mechanisms; Dev10x adds
mechanism 8 (action gating) and a meta-control layer (friction tuning).

## Two Directions

### Output backpressure — gates on the deliverable

Gates the agent's *output* before a human reviews it.
Mechanism numbers follow the article.

| # | Mechanism | Dev10x surface |
|---|-----------|---------------|
| 1 | Lint & test every iteration | `skills/py-test` (100% coverage), `hooks/scripts/ruff-format.py` (PostToolUse auto-format), CI `pytest-hooks.yml` / `pytest-servers.yml` |
| 2 | Manual testing | `skills/playwright`, `skills/qa-self` (staging + screenshot evidence), `skills/qa-scope` |
| 3 | Benchmarking | `.claude/rules/performance.md` baseline, `tests/benchmarks/` — gate exists but CI wiring is a known gap (GH-432) |
| 4 | Review agents | 8 specs in `.claude/agents/` + plugin-distributed `agents/` (code-reviewer, architect-*, reviewer-*), `claude-code-review.yml`, `skills/gh-pr-review`, `skills/review` + `review-fix` |
| 5 | Planning reviews | `skills/scope`, `ticket-scope`, `project-scope`, `adr`, `adr-evaluate` (adversarial architect panel); `work-on` Phase 3 plan-approval gate |
| 6 | Visual design review | `qa-self` screenshots — no automated diff against design specs today (future: perceptual-diff gate, project-flag-gated) |
| 7 | PR monitoring | `skills/gh-pr-monitor` (background CI + comment watcher, auto-fixup), `gh-pr-doctor`, privacy audit CI |

### Action backpressure — gates on the action before it runs

**Mechanism 8** (Dev10x-specific): `PreToolUse` hooks intercept every
Bash / file-write / MCP call and BLOCK unsafe actions before they
execute. This is the strongest and most distinctive backpressure surface
in the plugin.

**14 validators DX001–DX014** (`src/dev10x/validators/`):

| Rule ID | Validator | What it gates |
|---------|-----------|---------------|
| DX001 | safe-subshell | Prevents subshell execution patterns |
| DX002 | command-substitution | Blocks unsafe `$()` / backtick expansion |
| DX003 | execution-safety | Guards against dangerous execution patterns |
| DX004 | sql-safety | Blocks SQL writes outside `transaction.atomic` |
| DX005 | pr-base | Enforces correct PR base branch |
| DX006 | skill-redirect | Redirects raw CLI to the documented skill |
| DX007 | prefix-friction | Catches env-var prefixes on git/gh |
| DX008 | commit-jtbd | Enforces outcome-focused commit titles |
| DX009 | redundant-fetch | Warns on redundant git fetch calls |
| DX010 | bash-aggregation | Blocks `&&`/`;` command chaining |
| DX011 | pipeline-allow | Prevents raw pipe chains |
| DX012 | safe-expansion | Guards unsafe shell variable expansion |
| DX013 | mcp-prefix | Prevents MCP tool names in bash blocks |
| DX014 | sensitivity-target | Blocks writes to sensitivity-governed paths |

Profile tiers: `minimal` (DX001–DX005, safety-critical only),
`standard` (default, adds skill-redirect + friction validators),
`strict` (adds JTBD commit enforcement). Lower tiers always run at
higher tiers.

See `.claude/rules/hook-patterns.md` for profile tier table and
validator registration pattern.

## Meta-Control: Tunable Backpressure

**`friction_level`** in `session.yaml` controls how aggressively gates
fire — without changing *which* gates exist.

| Level | Effect |
|-------|--------|
| `strict` | All gates fire, always block for user input |
| `guided` | All gates fire, recommended option highlighted (default) |
| `adaptive` | Auto-select `(Recommended)` options; `ALWAYS_ASK` gates still fire |

Key rule: `adaptive` changes the *pace* at gates, not the *rules* of
the skill body. A skill's `TaskCreate` / safety-check / merge-checklist
steps all run at every friction level.

Full contract: `references/friction-levels.md`.

## Completion Gates

Completion gates enforce output quality at the end of a work unit.
They form the final backpressure layer before a human reviews anything.

| Gate | When it fires | What it checks |
|------|--------------|----------------|
| `verify-acc-dod` | End of every plan | All acceptance criteria checked (auto or manual per friction level) |
| `gh-pr-merge` 8-point check | Before merge | CI green, unresolved threads, draft state, mergeability, working copy, fixup commits, approval, branch protection |
| Never-empty task list | Always | At least one `Verify AC` task remains open until the supervisor confirms |
| `spec-update` / `spec-sync` | Around implementation | Spec touched if spec-governed file changes; enforces Golden Rule |

See `references/friction-levels.md` §Acceptance Criteria and
`skills/gh-pr-merge/SKILL.md` for the pre-merge checklist.

## Decision Gates (Skill-Level Backpressure)

Skills with `AskUserQuestion` gates create micro-backpressure at
blocking decision points within a workflow.

- All gates must be declared with **`REQUIRED: Call AskUserQuestion`**
  in SKILL.md (not plain text — plain text allows agents to auto-proceed)
- `ALWAYS_ASK` gates fire at all friction levels, including adaptive
- Non-`ALWAYS_ASK` gates auto-select their `(Recommended)` option
  under adaptive friction

Full pattern: `.claude/rules/skill-gates.md`.

## Architecture Summary

```
Action backpressure (mechanism 8)
  └─ PreToolUse validators DX001–DX014
       └─ Profile tiers: minimal / standard / strict
       └─ Tunable via friction_level in session.yaml

Output backpressure (mechanisms 1–7)
  ├─ Lint & test (1): ruff-format hook + py-test skill + CI
  ├─ Manual testing (2): playwright / qa-self / qa-scope
  ├─ Benchmarking (3): tests/benchmarks/ [CI wiring pending GH-432]
  ├─ Review agents (4): .claude/agents/ + agents/ + claude-code-review.yml
  ├─ Planning reviews (5): scope / adr / adr-evaluate / work-on Phase 3
  ├─ Visual design review (6): qa-self screenshots [diff gate not wired]
  └─ PR monitoring (7): gh-pr-monitor + gh-pr-doctor

Completion gates
  ├─ verify-acc-dod (end-of-plan ACC check)
  ├─ gh-pr-merge 8-point pre-merge check
  ├─ Never-empty task list invariant
  └─ spec-update / spec-sync Golden Rule

Decision gates (skill-level)
  └─ AskUserQuestion gates in skills (ALWAYS_ASK = fire at all levels)

Meta-control
  └─ friction_level: strict / guided / adaptive
```

## Known Gaps (from GH-430 audit)

1. **Benchmarking not a CI gate** (GH-432, P1): `tests/benchmarks/`
   exist but no workflow blocks on regression.
2. **Coverage not CI-enforced** (GH-433, P1): `py-test` enforces
   coverage when invoked; no workflow uses `--cov-fail-under`.
3. **Spec-drift not action backpressure** (GH-434, P2): `spec-update`/
   `spec-sync` enforce the Golden Rule only if called; no PreToolUse
   hook blocks edits to spec-governed files.
4. **No visual-diff gate** (future/optional, P3): `qa-self` captures
   screenshots but does not diff against design baselines.

## Related Documents

| Document | Role |
|----------|------|
| `.claude/rules/hook-patterns.md` | Validator registration, profile tiers, DX rule IDs |
| `references/friction-levels.md` | Friction level contract, adaptive behavior, completion gates |
| `.claude/rules/skill-gates.md` | Decision gate pattern, ALWAYS_ASK marking |
| `.claude/rules/performance.md` | CLI startup baseline, benchmark profiling |
| `references/permission-architecture.md` | Permission → hook execution order |
| `src/dev10x/validators/` | Validator implementations |
| `hooks/hooks.json` | Hook entry points |
