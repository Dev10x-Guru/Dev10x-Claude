---
name: Dev10x:qa-self
description: >
  Execute QA test cases on staging using headless Playwright, capture
  screenshot and video evidence, upload to Linear, and post structured
  results.
  TRIGGER when: QA ticket has test cases to execute against staging
  and evidence is needed.
  DO NOT TRIGGER when: analyzing PR for QA needs (use Dev10x:qa-scope),
  or running unit/integration tests (use test skill).
user-invocable: true
invocation-name: Dev10x:qa-self
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/playwright/scripts/:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/qa-self/scripts/:*)
  - AskUserQuestion
---

# Self-QA — Automated Staging Test Execution

Execute QA regression test cases on staging using headless
Playwright, capture screenshot and video evidence, and post
structured results to Linear.

## Instructions

The full workflow — test case discovery, Playwright execution,
evidence capture, Linear upload, result formatting — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` calls documented there are
REQUIRED.

## Gates

Two blocking gates in `instructions.md` are enforced with
`AskUserQuestion` — never a plain-text question:

1. **Test-failure recovery** (Phase 3) — fix and retry / skip the
   failing case / abort.
2. **Evidence review** (Phase 4.4) — approve the upload / re-capture /
   abort. Artifacts are verified by
   `scripts/verify-evidence.py` (Phase 4.1) and reviewed **locally**
   before anything reaches Linear: evidence trails on a ticket are
   append-only, so a bad take can only be superseded, never withdrawn.
