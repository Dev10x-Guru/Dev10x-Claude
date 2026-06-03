# Dev10x:playbook — Playbook Manager (Instructions)

## Overview

A **playbook** is a reusable, customizable set of steps that an
orchestration skill follows. Any skill can become playbook-powered
by placing a `references/playbook.yaml` in its directory.

This skill provides a guided interface for viewing and customizing
playbooks so users never need to edit raw YAML.

### Discovery

A skill is playbook-powered when it has:
```
skills/<skill-name>/references/playbook.yaml
```

This convention requires no front matter changes — the file's
presence is sufficient.

### Storage

User overrides follow the resolution order in
`references/config-resolution.md`:

| Tier | Path | Scope |
|------|------|-------|
| 1 | `.claude/Dev10x/playbooks/<key>.yaml` | Project-local |
| 2 | `~/.config/Dev10x/playbooks/<key>.yaml` | Global with repo mapping |

Where `<key>` is the skill directory name (e.g., `work-on`,
`release-notes`).

**Tier 2 (global)** uses `projects[].match` globs so one file
can serve multiple repos. See `references/config-resolution.md`
for the YAML format.

### Resolution Order

When loading a play, resolve in this order:
1. Project-local (`.claude/Dev10x/playbooks/<key>.yaml`)
2. Global with repo matching (`~/.config/Dev10x/playbooks/<key>.yaml`);
   fall back to `~/.claude/memory/Dev10x/playbooks/<key>.yaml` for
   backwards compatibility when the XDG path is absent.
3. Defaults from the skill's `references/playbook.yaml`

Within the resolved file, apply overrides in this order:
1. Non-persistent overrides (`persist: false`) — use once, then remove
2. Persistent overrides (`persist: true`) — reuse across sessions
3. Defaults section

## Orchestration

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Manage playbooks", activeForm="Managing playbooks")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Subcommands

Parse the arguments to determine the subcommand:

| Arguments | Subcommand | Action |
|-----------|-----------|--------|
| (none) or `list` | List | Show all playbook-powered skills |
| `view <skill> [<play>]` | View | Show plays for a skill (or one play) |
| `edit <skill> <play>` | Edit | Guided editing of a play |
| `reset [<skill> [<play>]]` | Reset | Reset overrides to defaults |

If `<skill>` is ambiguous, match against both directory name and
invocation name (e.g., `work-on` matches `Dev10x:work-on`).

---

## Subcommand: List

Scan all installed skill directories for `references/playbook.yaml`.

**Steps:**

1. Glob for `${CLAUDE_PLUGIN_ROOT}/skills/*/references/playbook.yaml`
   and any other plugin skill directories
2. For each found, read the YAML to count plays and get descriptions
3. Read user override files to detect customizations
4. Display:

```
## Playbook-Powered Skills

| Skill | Plays | Customized? |
|-------|-------|-------------|
| Dev10x:work-on | 5 (feature, bugfix, pr-continuation, local-only, investigation) | feature ✎ |
| tt:e2e-debug | 2 (investigate, fix) | — |

Use `/Dev10x:playbook view <skill>` to inspect plays.
Use `/Dev10x:playbook edit <skill> <play>` to customize.
```

---

## Subcommand: View

Show plays for a specific skill, or drill into one play.

**Steps:**

1. Locate the skill's `references/playbook.yaml`
2. Read it and any user overrides
3. If `<play>` specified: show that play's full step tree
4. If no `<play>`: show a summary of all plays in the skill

**Play detail format:**

```
## Dev10x:work-on → feature

**Prompt:** Use when a ticket describes new functionality...

| # | Type | Step | Skills | Children |
|---|------|------|--------|----------|
| 1 | detailed | Set up workspace | Dev10x:ticket-branch | — |
| 2 | detailed | Draft Job Story | Dev10x:jtbd | — |
| 3 | epic | Design implementation approach | — | 3 children |
|   |   | ├─ Read relevant code | — | |
|   |   | ├─ Identify affected components | — | |
|   |   | └─ Propose approach | — | |
| 4 | epic | Implement changes | — | — |
| 5 | epic | Verify | — | 2 children |
| — | — | [FRAGMENT: shipping-pipeline] | — | 9 steps |

**Source:** defaults (no user override)
```

When displaying a play that contains fragment references, show
`[FRAGMENT: <name>]` with the step count. If the user asks for
full expansion, resolve the fragment inline and display all steps.

If an override exists, show both so the user can compare.

---

## Subcommand: Edit

Guided editing of a play. Users describe changes in natural
language rather than editing YAML.

**Steps:**

1. Show the current play (same as View)
2. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
   Options:
   - **Add step** — Insert a new step at a specific position
   - **Remove step** — Remove a step by number
   - **Reorder steps** — Move a step to a different position
   - **Edit step** — Change a step's subject, type, prompt, or skills

   When editing a play that uses fragment references, the user can
   also choose to inline a fragment (replace `- fragment: <name>`
   with the expanded steps for further editing) or replace a
   sequence of steps with a fragment reference.

3. Based on the user's choice, gather details:

   **Add step:**
   - Ask: position (before/after which step), subject, type
     (detailed/epic), skills (optional), prompt (optional)
   - If epic: ask if it should have pre-templated children

   **Remove step:**
   - Confirm which step to remove (by number)
   - Warn if removing a step that other skills depend on

   **Reorder steps:**
   - Ask which step to move and where

   **Edit step:**
   - Show the current step details
   - Ask what to change

4. Preview the modified play as a numbered tree
5. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
   Options:
   - **Save** — Write the override to the user's playbook file
   - **Continue editing** — Make more changes (loop back to step 2)
   - **Discard** — Abandon changes

6. If Save:
   - Read the user's playbook file for this skill (create if absent)
   - Add/update the override entry for this play
   - Set `persist: true` and `added: <today's date>`
   - Write to `~/.config/Dev10x/playbooks/<skill-key>.yaml`
     (global — preferred) or `.claude/Dev10x/playbooks/<skill-key>.yaml`
     (project-local). See `references/config-resolution.md`.

**Override format:**

```yaml
overrides:
  - play: feature
    persist: true
    added: 2026-03-11
    steps:
      - subject: Set up workspace
        type: detailed
        skills: [Dev10x:ticket-branch]
      # ... full step list
```

---

## Subcommand: Reset

Reset overrides to the skill's default playbook.

**Steps:**

1. If `<skill>` and `<play>` specified: reset that one play
2. If only `<skill>`: reset all overrides for that skill
3. If neither: show all overrides across all skills
4. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
   Options:
   - **Reset** — Remove the selected override(s)
   - **Cancel** — Keep current overrides

---

## Playbook YAML Schema

Each skill's `references/playbook.yaml` follows this structure:

```yaml
# Fragments — reusable step sequences
fragments:
  <fragment-name>:
    - subject: Step title (required)
      type: detailed | epic (required)
      prompt: ... (optional)
      skills: [...] (optional)
      agent: ... (optional)

# Top-level: map of play names to play definitions
defaults:
  <play-name>:
    prompt: >
      Heuristic guidance for when this play applies and
      how to adapt it based on context.
    steps:
      - subject: Step title (required)
        type: detailed | epic (required)
        prompt: ... (optional)
        skills: [skill1, skill2] (optional)
        steps: [] (optional — pre-templated epic children)
        condition: hint (optional)
        modes:            # per-mode overrides (optional)
          <mode-name>: skip | {subject, prompt, skills, ...}
        friction:         # per-friction-level overrides (optional)
          adaptive: skip: true | {prompt, subject, skills, ...}
          strict: {prompt, ...}
      - fragment: <fragment-name> (optional — inline reference)
        condition: hint (optional — applied to all expanded steps)
        prompt: ... (optional — overrides prompt on all expanded steps)

overrides: []  # populated by this skill when user customizes

# User override files may also define:
# active_modes: [solo-maintainer]  — activate structural modes
# mode_extensions:                 — extend modes per project
#   <mode-name>:
#     steps:
#       "Step subject": {prompt: ..., skills: [...]}
# fragments:
#   <fragment-name>:
#     - subject: ... (same schema as default fragments)
# These shadow default fragments with the same name.
```

### Modes and Friction

**Modes** are structural — they change *what* steps exist and
*who* is involved (e.g., solo-maintainer removes reviewer steps).
**Friction levels** are behavioral — they change *how* gates fire
(strict/guided/adaptive). These are orthogonal dimensions.

Steps declare `modes:` and `friction:` inline. The resolver
applies modes first, then friction, so mode-added steps can
have their own friction mappings.

See `references/execution-modes.md` for the full mode taxonomy
and `references/friction-levels.md` for friction behavior.

**Project activation** (global playbook with repo mapping):
```yaml
# ~/.config/Dev10x/playbooks/work-on.yaml
projects:
  - match: "example-org/*"
    active_modes: [solo-maintainer]
```

**Session activation (set by work-on Phase 0):**
```yaml
# .claude/Dev10x/session.yaml
friction_level: adaptive
active_modes: [solo-maintainer]
```

### Fragment References

A step entry with `fragment: <name>` is replaced at resolution
time by the steps from the named fragment. The reference may
carry a `condition` override that applies to every expanded step.

Fragments work in both default playbooks and user override files.
User overrides can define their own `fragments:` section and
reference those fragments (or default fragments) in their plays.

**Resolution rules:**
1. Load the `fragments` map from the user override file (if present)
2. Merge with fragments from the default playbook YAML; user
   fragments shadow defaults with the same name
3. **Field inheritance on shadowing (GH-938):** When a user
   fragment shadows a default, match steps by `subject`. For
   each matched step, inherit `skills`, `agent`, `model`, and
   `modes` from the default if the user step omits them. To
   explicitly remove a field, set it to `[]` or `{}`. This
   makes `skills:` "sticky" — preventing silent delegation
   bypass when users customize only the `prompt:`.
4. Walk the step list; when `fragment: <name>` is found,
   look up the name in the merged fragments map
5. Copy fragment steps inline, applying `condition` from the
   reference to each expanded step
6. `subject` and `type` from fragment steps are immutable —
   only `condition` and `prompt` can be overridden at the
   reference site
7. Detect circular references (max depth 3)
8. Missing fragment → clear error, do not silently skip

See `references/playbook.yaml` for the full work-on playbook
with all 5 plays as a reference implementation.

## How to Make a Skill Playbook-Powered

1. Create `skills/<your-skill>/references/playbook.yaml`
2. Define one or more plays with steps following the schema above
3. In your SKILL.md orchestration section, load the playbook using
   the 3-tier resolution in `references/config-resolution.md`:
   ```
   1. .claude/Dev10x/playbooks/<key>.yaml (project-local)
   2. ~/.config/Dev10x/playbooks/<key>.yaml (global + repo match)
      → fallback: ~/.claude/memory/Dev10x/playbooks/<key>.yaml
   3. ${CLAUDE_PLUGIN_ROOT}/skills/<skill>/references/playbook.yaml
   ```
4. The `Dev10x:playbook` skill automatically discovers your skill

**Loading pattern for orchestration skills:**
```
Read(.claude/Dev10x/playbooks/<key>.yaml)
  → if absent, Read(~/.config/Dev10x/playbooks/<key>.yaml) + repo match
    → if absent (backwards compat), Read(~/.claude/memory/Dev10x/playbooks/<key>.yaml)
  → if absent, Read(${CLAUDE_PLUGIN_ROOT}/skills/<skill>/references/playbook.yaml)
  → resolve: overrides first, then defaults
  → validate version (warn on mismatch)
  → create tasks from steps
```

### Version validation (GH-910)

The default playbook includes a `version:` field matching the
plugin version. After loading, compare the playbook version
with the plugin version. On mismatch, warn:
"Playbook version {playbook_version} differs from plugin
{plugin_version}. Some steps may be outdated."

## Integration with Orchestration Skills

Any orchestration skill can load its playbook using the resolution
order above. When presenting the play to the user, it should note:
"Customize this playbook with `/Dev10x:playbook edit <skill> <play>`."

If a user asks to customize during an active session, the
orchestrator can delegate to this skill mid-flight and then
reload the updated playbook.

---

## Examples

### Example 1: List all playbook-powered skills

**User:** `/Dev10x:playbook`

Shows all skills with `references/playbook.yaml`, their play
counts, and customization status.

### Example 2: View work-on plays

**User:** `/Dev10x:playbook view work-on`

Shows summary of all 5 plays (feature, bugfix, etc.) with
step counts and descriptions.

### Example 3: View a specific play

**User:** `/Dev10x:playbook view work-on bugfix`

Shows the full bugfix play with all steps, children, prompts,
and skill delegations in a readable tree format.

### Example 4: Customize a play for a project

**User:** `/Dev10x:playbook edit work-on feature`

1. Shows current feature play (10 steps)
2. User selects "Add step"
3. User says: "Add a 'Run e2e tests' step after Verify"
4. Skill creates the step with `skills: [tt:e2e-debug]`
5. Shows preview with 11 steps
6. User selects "Save"
7. Writes override to `~/.config/Dev10x/playbooks/work-on.yaml`

### Example 5: Future — e2e-debug with a playbook

Once `tt:e2e-debug` adds `references/playbook.yaml`:
```yaml
defaults:
  investigate:
    prompt: >
      Use when an e2e test failure needs root cause analysis.
    steps:
      - subject: Fetch CI run artifacts
        type: detailed
        prompt: Download screenshots, logs, and video from the failed run.
      - subject: Analyze failure pattern
        type: epic
        prompt: Compare against known flaky patterns and recent changes.
      - subject: Propose fix or report
        type: detailed
        prompt: Either implement a fix or document findings.
```

Then `/Dev10x:playbook view app-e2e-debug investigate` works
automatically — no changes to this skill needed.
