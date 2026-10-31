---
name: dev10x:skill-prune
invocation-name: dev10x:skill-prune
description: >
  Use when a project inherits dozens of skills it will never use after
  installing several plugins — so the skill listing stops spending
  context on frontend skills in a Django backend (or iOS setup in a web
  app) and skill matching stops picking the wrong one, without curating
  the list by hand every session.
  TRIGGER when: the user asks to prune, hide, or turn off irrelevant
  skills for this project, or after a new plugin install adds skills.
  DO NOT TRIGGER when: the user wants a plugin uninstalled everywhere
  (use /plugin), or wants a single setting changed (use update-config).
user-invocable: true
allowed-tools:
  - Bash(uvx dev10x skill prune-overrides:*)
  - Bash(dev10x skill prune-overrides:*)
  - Read
  - Edit(~/.config/Dev10x/skill-prune.yaml)
  - Glob
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# dev10x:skill-prune

**Announce:** "Using dev10x:skill-prune to hide the skills this project
will never use."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Prune irrelevant skills for this project", activeForm="Pruning skills")`

Mark completed after Step 5: `TaskUpdate(taskId, status="completed")`.

## What Claude Code can and cannot hide

| Skill kind | Listed as | How to hide it per project |
|------------|-----------|----------------------------|
| User or project skill | `deploy` | `skillOverrides: {"deploy": "off"}` |
| Plugin skill | `impeccable:audit` | **Not** by `skillOverrides` — only the whole plugin, via `enabledPlugins: {"impeccable@<marketplace>": false}` |

`skillOverrides` values: `off` (hidden everywhere), `user-invocable-only`
(only the user can call it), `name-only` (name listed, description
dropped), `on`. Claude Code documents that plugin skills ignore
`skillOverrides`, so the planner refuses plugin-skill names rather than
writing an entry that does nothing (GH-1627).

## Workflow

### Step 1: Read the project

Gather the stack cues — do not guess them from the directory name:

- `CLAUDE.md`, `README.md`
- `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `Gemfile`,
  `*.xcodeproj` (Glob for them at the repo root)
- Frontend markers: `*.svelte`, `*.tsx`, `*.astro`; mobile markers:
  `ios/`, `android/`

Write a one-line stack summary: "Django + Celery backend, no frontend,
no mobile".

### Step 2: Read the current state

1. Current overrides: `Read(.claude/settings.local.json)` — note the
   existing `skillOverrides` and `enabledPlugins`.
2. Allowlist: `Read(~/.config/Dev10x/skill-prune.yaml)` — its `keep:`
   names are never proposed. A missing file means no allowlist.
3. Installed plugin ids (`name@marketplace`): the `enabledPlugins`
   keys in `~/.claude/settings.json` and the project settings files.

**Re-run:** when overrides already exist, show them first and limit
the proposal to skills not yet decided — newly installed ones.

### Step 3: Classify the visible skills

Take the skill list from this session's skill listing. For each skill,
compare its description to the stack summary:

- **Clearly irrelevant** — targets a stack the project does not have
  (Svelte skills in a Django backend, iOS Sentry setup in a web app).
- **Probably irrelevant** — plausible but unlikely here (a marketing
  deck skill in an infra repo).
- **Keep** — matches the stack, is workflow-generic (git, PR, tests),
  or is on the allowlist.

Group plugin skills by plugin. Propose disabling a plugin only when
**every** skill it ships is irrelevant; otherwise list it under
"plugin skills that cannot be hidden one by one" and keep it.

Build the dry run and show its output as the proposed diff:

```bash
uvx dev10x skill prune-overrides --set <name>=off ... --disable-plugin <plugin@market> ...
```

stdout is one JSON object: `skill_changes`, `plugin_disables`,
`unchanged`, `kept_by_allowlist`, `plugin_skills_refused`. A
non-empty `plugin_skills_refused` means a plugin skill was proposed by
name — move it to a plugin decision instead.

### Step 4: Confirm

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). Show the
counts per category and the plugins to disable. Options:

- Hide clearly irrelevant (Recommended) — `off` for that category only
- Hide clearly and probably irrelevant — both categories
- User-invocable only — keep them callable by `/name`, out of Claude's
  automatic matching
- Review one by one — ask per skill, then apply the chosen set

**Allowlist offer.** When the user kept any name the classifier
proposed hiding, **REQUIRED: Call `AskUserQuestion`** once (do NOT use
plain text, `multiSelect: true`) listing those names. Options:

- Keep for this project only (Recommended) — nothing is persisted
- One option per kept name — add it to the `keep:` list in
  `~/.config/Dev10x/skill-prune.yaml` (via `Edit`) so no project is
  ever offered it again

**Scope.** The write target is project-local
`.claude/settings.local.json`. Writing user scope
(`~/.claude/settings.json`) or the checked-in `.claude/settings.json`
needs the user to ask for it explicitly — then pass `--settings <path>`.

### Step 5: Apply and report

Re-run the dry-run command with exactly the confirmed set plus
`--apply`. The command merges into existing `skillOverrides` and
`enabledPlugins` under a file lock and leaves every other key alone;
running it again reports `has_changes: false`.

Report what changed and say that it takes effect in the **next**
session.

## Common Mistakes

| Mistake | Consequence |
|---|---|
| Writing `impeccable:audit` into `skillOverrides` | Entry is ignored; the skill still loads and the user believes it is gone |
| Disabling a plugin because most of its skills are irrelevant | The one skill the project needed disappears with it |
| Writing to `~/.claude/settings.json` by default | Every other project loses those skills too |
| Hand-editing the settings JSON | Existing overrides are overwritten and re-runs are no longer idempotent |
