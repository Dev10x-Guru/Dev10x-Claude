# Playbook-Powered Skills

Pattern for skills that define multi-mode workflows in YAML playbooks.

## What is a Playbook?

A playbook is a YAML file that separates complex workflow definitions
from the main SKILL.md. It enables skills to adapt behavior based on
context (e.g., responding to single comments vs. batches).

**Location**: `skills/<name>/references/playbook.yaml`

## Structure

### Playbook File Layout

```yaml
defaults:
  single:
    # steps for processing one item
    - subject: "Analyze..."
      type: "analyze"
      prompt: "..."
      condition: "item.type == 'pr_comment'"
  batch:
    # steps for processing multiple items
    - subject: "Plan..."
      type: "plan"
      prompt: "..."
```

**Key fields**:
- `defaults`: Root section containing play definitions
- `single`/`batch`: Play names (matched by mode detection in SKILL.md)
- `steps`: Array of workflow steps
- `subject`: Step description (used in TaskCreate)
- `type`: Step category (e.g., "analyze", "plan", "execute")
- `prompt`: Instruction for Claude to execute
- `model`: (Optional) Override model for agent dispatch (haiku/sonnet/opus)
- `condition`: (Optional) Python expression filtering when step runs

## When to Use Playbooks

**Use playbooks when:**
- A skill supports 2+ distinct modes (single item vs. batch)
- Workflow steps differ significantly per mode
- SKILL.md orchestration would exceed ~100 lines
- Customization via playbook overrides is needed

**Don't use playbooks when:**
- Skill has simple linear orchestration
- One-off conditional logic (use inline `condition` in SKILL.md instead)

## User Customization

Users can override playbooks using the 3-tier resolution order
(see `references/config-resolution.md`):

| Tier | Path | Scope |
|------|------|-------|
| 1 | `.claude/Dev10x/playbooks/<skill-name>.yaml` | Project-local |
| 2 | `~/.claude/memory/Dev10x/playbooks/<skill-name>.yaml` | Global + repo mapping |
| 3 | `${CLAUDE_PLUGIN_ROOT}/skills/<name>/references/playbook.yaml` | Plugin defaults |

Tier 2 (global) is preferred — one file serves multiple repos via
`projects[].match` globs. The skill loads this file at invocation,
allowing users to customize behavior without editing the plugin.

> **Note (GH-941):** The old `~/.claude/projects/<key>/memory/`
> path is removed. All tier 2 config lives under
> `~/.claude/memory/Dev10x/`.

## Reviewer Expectations

When reviewing a skill with playbook.yaml:

1. **YAML syntax** — Valid YAML structure, proper indentation
2. **Play name matching** — Each play in playbook (e.g., `single`,
   `batch`) must match a mode detection condition in SKILL.md
3. **Condition explanations** — Every `condition` field must be
   documented in SKILL.md (e.g., "Condition: `item.type == 'pr_comment'`
   ensures this step runs only for PR comments")
4. **Gate references** — If a step's prompt includes `AskUserQuestion`,
   verify SKILL.md marks it as "REQUIRED: Call AskUserQuestion"
5. **Tool alignment** — Verify `skills:` array in playbook matches
   `allowed-tools:` declarations in SKILL.md

## Example

**SKILL.md** (excerpt):
```yaml
orchestration:
  **Playbook-driven modes:**
  - Single comment (Condition: `len(comments) == 1`)
    → Load `playbook.yaml` play "single"
  - Batch comments (Condition: `len(comments) > 1`)
    → Load `playbook.yaml` play "batch"
```

**playbook.yaml** (excerpt):
```yaml
defaults:
  single:
    - subject: "Respond to one comment"
      prompt: "Review the comment and draft a response..."
      condition: "comment.resolved == false"
  batch:
    - subject: "Plan multi-comment strategy"
      prompt: "Analyze all comments and create a response plan..."
```

## Anti-Patterns

- ❌ Defining every step as optional with `condition` fields — this
  indicates the workflow should be linear, not multi-play
- ❌ Duplicating steps across plays — extract to a shared step template
- ❌ Playbook-only documentation — SKILL.md must still explain mode
  detection and play names
