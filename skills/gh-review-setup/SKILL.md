---
name: Dev10x:gh-review-setup
description: >
  Guided, discovery-driven setup of Claude code-review GitHub Actions on
  any repo. Detects the stack, lets you pick independently-skippable review
  modules (code review, PR hygiene, ADR distillation, lessons-learned,
  second-opinion), surfaces pros/cons for each strategy decision, then
  scaffolds generalized workflows + reviewer specs with zero
  project-identifying strings copied from any source project.
  TRIGGER when: standing up Claude code review on a repo that has none, or
  adding/regenerating review automation on an existing repo.
  DO NOT TRIGGER when: running an existing review (use Dev10x:gh-pr-review
  or Dev10x:review), or monitoring a PR (use Dev10x:gh-pr-monitor).
user-invocable: true
invocation-name: Dev10x:gh-review-setup
allowed-tools:
  - AskUserQuestion
  - Bash(gh:*)
  - Bash(rg:*)
  - Bash(git rev-parse:*)
  - Bash(git remote:*)
  - Bash(mkdir -p:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Write(.github/workflows/**)
  - Write(.claude/**)
  - Write(references/**)
  - Write(CLAUDE.md)
  - mcp__plugin_Dev10x_cli__mktmp
  - mcp__plugin_Dev10x_cli__detect_tracker
  - mcp__plugin_Dev10x_cli__detect_base_branch
---

# Dev10x:gh-review-setup — Guided Code-Review Provisioning

**Announce:** "Using Dev10x:gh-review-setup to provision Claude
code-review GitHub Actions on this repo."

Scaffolds an opinionated-but-flexible Claude code-review pipeline. Every
decision is **discovered, not assumed**: path globs, the domain-routing
table, and the reviewer roster are all derived from what Phase 1 finds —
never copied from a reference project. Each review module is an independent
workflow file with its own trigger and model tier, so users adopt and
budget each one separately.

## When to Use

- A repo has no `.claude/` review automation and you want to stand it up.
- An existing repo needs an additional module (e.g., add lessons-learned).
- You want review automation tuned to a non-Python stack (skills, shell,
  config, markdown) — discovery handles it.

## Arguments

Optional. Accepts a target directory (defaults to the current repo) or a
free-text hint (e.g. `"config repo, no tracker"`). No arguments runs full
interactive discovery.

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard). The full five-phase workflow lives in
[`instructions.md`](instructions.md) — Read it now and follow it
end-to-end.

**Auto-advance:** Complete each phase and immediately start the next — no
checkpoints under adaptive friction. The only pauses are the REQUIRED
decision gates below (module selection + strategy choices); these are
genuine A/B choices that change the generated output.

**REQUIRED: Create tasks before ANY work.** Execute these `TaskCreate`
calls at startup:

1. `TaskCreate(subject="Phase 1: Discover stack & environment", activeForm="Discovering stack")`
2. `TaskCreate(subject="Phase 2: Pick review modules", activeForm="Selecting modules")`
3. `TaskCreate(subject="Phase 3: Resolve strategy decisions", activeForm="Resolving strategies")`
4. `TaskCreate(subject="Phase 4: Scaffold workflows & specs", activeForm="Scaffolding")`
5. `TaskCreate(subject="Phase 5: Verify & hand off", activeForm="Verifying")`

Set sequential dependencies (each phase blocked by the previous).

## Phase Summary

| Phase | Does | Reference |
|-------|------|-----------|
| 1 Discover | Detect languages/file-types, existing `.claude/` structure, tracker, review secrets, default branch | [`references/discovery.md`](references/discovery.md) |
| 2 Pick modules | Toggle each module on/off with discovery-driven defaults | [`references/modules.md`](references/modules.md) |
| 3 Strategy | Review depth, model tiering, action pinning, API-key strategy, lessons destination, notifications — each with pros/cons + a recommended default | [`references/strategies.md`](references/strategies.md) |
| 4 Scaffold | Render generalized workflows + routing table + reviewer specs + shared review references from templates | [`references/scaffold.md`](references/scaffold.md), [`references/templates/`](references/templates/) |
| 5 Verify | Confirm required secrets, summarize installed workflows + chosen strategies, remind to open the landing PR | `instructions.md` § Phase 5 |

## Decision Gates (REQUIRED)

These are blocking choices that change the generated artifacts. Each MUST
use `AskUserQuestion` — never plain text. Full call specs and per-option
pros/cons live in [`references/modules.md`](references/modules.md) and
[`references/strategies.md`](references/strategies.md).

1. **Module selection** (Phase 2) — **REQUIRED: Call `AskUserQuestion`**
   (multiSelect). Pre-checks reflect discovery defaults; every module is
   independently skippable. Skipping ADR/hygiene is first-class, not a hack.
2. **Strategy decisions** (Phase 3) — **REQUIRED: Call `AskUserQuestion`**
   for each decision whose recommended default the user has not pre-stated.
   Batch related decisions into one call (1–4 questions). Each option
   carries its pros/cons in the `description`.

Under `friction_level: adaptive`, auto-select the recommended option for
each gate and proceed — but still emit the tool call so the user retains
override capability (per `essentials.md` § Decision Gates).

## Guardrails (Hard Rules)

- **Zero project-identifying strings.** Every rendered workflow, prompt,
  routing table, and example MUST be generalized at generation time. Run
  the sanitization pass in [`references/sanitization.md`](references/sanitization.md)
  and the Phase 5 grep gate before declaring done. A source project name
  (`Dev10x`, `TireTutor`, repo slugs, vendor/domain nouns) leaking into the
  output is an acceptance-criteria failure.
- **Discovery-driven, never copied.** Do NOT read a source project's
  workflow and edit it in place. Render from `references/templates/` with
  placeholders filled by Phase 1 discovery.
- **Lessons-learned guardrails are mandatory** when that module is
  selected: scope-lock to `.claude/` + `CLAUDE.md`, domain-name
  sanitization (prose AND code examples), per-file size budgets, and the
  single-open-draft-PR lock. See `references/sanitization.md`.
- **Secrets are out of scope (v1).** The skill prints exactly which
  secrets to add and where; it never creates them.
- **GitHub only (v1).** No GitLab/Bitbucket scaffolding.

## Self-Improvement

Each run appends a structured setup record (chosen modules, strategies,
friction) under `.claude/Dev10x/gh-review-setup/` and emits a skill-audit
hook so the scaffolder's own defaults can be tuned over time — the same
mechanism as `Dev10x:skill-audit`. See `instructions.md` § Phase 5.

## Integration

```
Dev10x:gh-review-setup   (provisions review automation — this skill)
├─ Dev10x:gh-pr-review   (runs a review on a PR)
├─ Dev10x:review         (self-review before PR)
└─ Dev10x:gh-pr-monitor  (watches CI + review comments)
```
