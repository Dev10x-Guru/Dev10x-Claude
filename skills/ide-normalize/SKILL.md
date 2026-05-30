---
name: Dev10x:ide-normalize
description: >
  Normalize PyCharm .idea/ configuration after creating or copying a new git
  worktree. Fixes stale module-name references, disables ADD_CONTENT_ROOTS /
  ADD_SOURCE_ROOTS defaults that conflict with editable installs, backfills the
  Django facet settingsModule, and detects the PyCharm uv-SDK FLAVOR_DATA gap.
  TRIGGER when: a new worktree has been created and the .idea/ directory was
  copied from a sibling worktree or the main repo, OR when PyCharm crashes on
  launch with ModuleNotFoundError after opening a new worktree.
  DO NOT TRIGGER when: the project has no .idea/ directory or does not use
  PyCharm / JetBrains IDEs.
user-invocable: true
invocation-name: Dev10x:ide-normalize
allowed-tools:
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(ls:*)
  - Read
  - Edit
---

# IDE Normalize

Fix PyCharm `.idea/` configuration drift that occurs when a `.idea/` directory
is copied from a parent repo into a new git worktree. Also detects the PyCharm
uv-SDK `FLAVOR_DATA` gap that causes crashes on first launch.

## Design Decision

This is a **separate skill** rather than a step inside `Dev10x:git-worktree`
for two reasons:

1. **Retroactive use**: teams often create worktrees without this skill, or
   before this fix landed. A standalone skill lets them normalize existing
   worktrees without recreating them.
2. **Separation of concerns**: `Dev10x:git-worktree` handles git mechanics.
   IDE configuration is a separate concern that may apply to non-worktree
   scenarios (e.g., first-time clone on a new machine).

`Dev10x:git-worktree` documents this skill in its Python/uv template notes as
a recommended post-checkout step.

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Normalize IDE configuration", activeForm="Normalizing .idea/")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

**Announce:** "Using Dev10x:ide-normalize to fix PyCharm .idea/ configuration."

## Workflow

### Step 1: Locate .idea/ and Detect Project Context

Run:
- `find . -maxdepth 1 -name ".idea" -type d` — confirm `.idea/` exists
- `find . -maxdepth 1 -name "modules.xml" -type f` — fallback if no `.idea/`
- Read `.idea/modules.xml` to get the canonical module name(s)
- Read `.idea/workspace.xml` to identify stale module name references
- Check `git worktree list` to get current worktree path and parent repo path

If `.idea/` is not found, report "No .idea/ directory found — nothing to
normalize" and mark the task complete.

### Step 2: Fix Stale Module-Name References

In `.idea/workspace.xml`, module names often refer to the parent repo name
(e.g., `<module name="encom-corp" />`) instead of the current project name
(e.g., `<module name="encom-pos" />`).

Detection:
- Read `.idea/modules.xml` — the `<module>` elements name the correct
  module(s) for this project.
- Grep `.idea/workspace.xml` for `<module name="` — compare against the
  canonical names from `modules.xml`.

Fix: use Edit to replace each stale reference with the correct module name.

Report how many references were updated (e.g., "Updated 3 module-name
references in workspace.xml").

### Step 3: Disable ADD_CONTENT_ROOTS and ADD_SOURCE_ROOTS

`.idea/workspace.xml` run configs often have:

```xml
<option name="ADD_CONTENT_ROOTS" value="true" />
<option name="ADD_SOURCE_ROOTS" value="true" />
```

These defaults inject `<repo>/src` onto `PYTHONPATH`, which conflicts with
editable installs (PEP 660 / `pip install -e .` / uv workspace members).
When New Relic or any other `sitecustomize`-bootstrapping agent is installed,
this side channel activates the bootstrap loader, which then fails under
uv-managed interpreters.

Fix: Edit every occurrence in `.idea/workspace.xml` to `value="false"`.

See [`references/pep660-pythonpath-conflict.md`](references/pep660-pythonpath-conflict.md)
for full explanation and background.

Report: "Disabled ADD_CONTENT_ROOTS/ADD_SOURCE_ROOTS on N run configurations."

### Step 4: Backfill Django settingsModule

In `.idea/workspace.xml`, Django run configs often have:

```xml
<option name="settingsModule" value="" />
```

Detection:
- Grep for `settingsModule.*value=""` — empty settingsModule entries
- Look for the Django settings module path by checking:
  - `manage.py` — `os.environ.setdefault('DJANGO_SETTINGS_MODULE', ...)` line
  - `pyproject.toml` or `setup.cfg` — `[tool.django]` or `DJANGO_SETTINGS_MODULE`

If the settings module can be determined, fill in each empty `settingsModule`
value. If it cannot be determined, report the empty entries and ask the user to
provide the correct module path before continuing.

**REQUIRED: Call `AskUserQuestion`** if the Django settings module cannot be
auto-detected. Options:
- "Enter the settings module path (e.g. `config.settings.local`)"
- "Skip — I'll fix this manually"

### Step 5: Detect PyCharm uv-SDK FLAVOR_DATA Gap

After PyCharm creates a `uv (<worktree-name>)` SDK entry for a new worktree,
the `jdk.table.xml` entry is missing `UV_VENV_PATH` / `UV_TOOL_PATH` and has
an empty `FLAVOR_DATA="{}"`. This causes PyCharm to construct
`uv run /full/path/.venv/bin/python manage.py …` (wrong) instead of
`uv run python manage.py …` (correct), crashing with:

```
ModuleNotFoundError: No module named 'collections.abc'
```

Detection:
- Read `~/.config/JetBrains/PyCharm*/options/jdk.table.xml` (glob — ask
  user for path if multiple PyCharm versions exist)
- Find SDK entries whose `ASSOCIATED_PROJECT_PATH` matches the current
  worktree path
- Check if `FLAVOR_DATA` is `"{}"` or if `UV_VENV_PATH` / `UV_TOOL_PATH`
  attributes are missing

See [`references/pycharm-uv-sdk-gap.md`](references/pycharm-uv-sdk-gap.md)
for the full diagnosis, broken vs working SDK comparison, and patch recipe.

**If gap detected:**

**REQUIRED: Call `AskUserQuestion`** — PyCharm must be closed to patch
`jdk.table.xml` safely (the IDE overwrites the file on exit). Options:
- "Patch automatically (PyCharm must be closed)"
- "Show me the manual fix instead"
- "Skip — I'll handle this later"

If patching: mirror `UV_VENV_PATH`, `UV_TOOL_PATH`, and `FLAVOR_DATA` from
the parent project's SDK entry. Report the patch applied.

If showing manual fix: display the `references/pycharm-uv-sdk-gap.md` recipe.

### Step 6: Summary Report

Print a summary:

```
IDE normalize complete:
  module-name fixes: N references updated
  run config flags:  N ADD_CONTENT_ROOTS/ADD_SOURCE_ROOTS set to false
  Django settings:   <filled / skipped / N entries still empty>
  uv SDK gap:        <patched / shown / not detected / skipped>
```

Mark the task complete.
