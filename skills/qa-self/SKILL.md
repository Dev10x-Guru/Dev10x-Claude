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
