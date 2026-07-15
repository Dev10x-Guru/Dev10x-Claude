---
name: Dev10x:playbook
description: >
  View and customize playbooks (step-by-step procedures) for any
  orchestration skill. List playbook-powered skills, inspect plays,
  edit steps through a guided flow, or reset to defaults.
  TRIGGER when: user wants to view, edit, or customize playbook
  workflows for skills.
  DO NOT TRIGGER when: executing a playbook-powered skill (handled
  automatically by Dev10x:work-on or other orchestrators).
user-invocable: true
invocation-name: Dev10x:playbook
allowed-tools:
  - Read(.claude/Dev10x/playbooks/*.yaml)
  - Read(~/.config/Dev10x/playbooks/*.yaml)
  - Read(~/.claude/memory/Dev10x/playbooks/*.yaml)
  - Edit(.claude/Dev10x/playbooks/*.yaml)
  - Edit(~/.config/Dev10x/playbooks/*.yaml)
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# Dev10x:playbook — Playbook Manager

Guided interface for viewing and customizing playbook YAML files
(`references/playbook.yaml` within any playbook-powered skill)
so users never need to edit raw YAML.

## Instructions

The full workflow — discovery, inspection, guided edit flow,
reset to defaults, tier resolution — lives in
[`instructions.md`](instructions.md).

When this skill is invoked, Read `instructions.md` now and
follow it end-to-end. `TaskCreate` calls and `AskUserQuestion`
gates documented there are REQUIRED.
