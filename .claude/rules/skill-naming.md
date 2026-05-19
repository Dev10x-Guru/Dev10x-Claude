---
paths:
  - "skills/**"
---

# Skill Naming Convention

Rules for naming skill directories and invocation names in
this plugin.

## Directory Names

Use the plain feature name. No `dx-` prefix on directories.

**Good:**
```
skills/git-worktree/
skills/skill-audit/
skills/park/
skills/linear/
```

**Bad:**
```
skills/dx-git-worktree/
skills/dx-skill-audit/
```

*Why?* The filesystem already scopes skills to this plugin's
`skills/` directory. Adding a redundant prefix clutters tab
completion and directory listings.

## Invocation Name (SKILL.md `name:` field)

Use the `Dev10x:<feature-name>` format in the SKILL.md front matter.

**Good:**
```yaml
name: Dev10x:git-worktree
name: Dev10x:skill-audit
name: Dev10x:park
```

**Bad:**
```yaml
name: git-worktree
name: skill-audit
```

*Why?* This is an intentional **branding decision**. Claude Code
auto-constructs `<PluginName>:<dir-name>` identifiers for the
system-reminder listing (e.g., `Dev10x:git-commit`), so the prefix
is technically redundant for skill resolution. However, we include
it explicitly in `name:` for:
- **Brand consistency** — the `Dev10x:` prefix is visible in MOTD
  listings and `Skill()` invocations across all projects
- **Collision avoidance** — explicit prefix prevents ambiguity when
  multiple plugins define similarly-named skills
- **Self-documenting** — skill identity is clear without needing
  plugin context

Note: official plugins (superpowers, svelte, hookify) omit the
prefix and rely on auto-construction. Our explicit prefix is a
deliberate divergence for branding.

## Suffix Encodes Execution Shape (GH-217)

The suffix of a skill name tells the reader *how* the skill
behaves — deterministic vs heuristic. Pick the suffix from the
shape of the work, not from "what sounds right".

### `<resource>-<verb>` → mechanical

Deterministic flow, small decision tree, typically single-agent,
≤ 200 lines of orchestration. Output shape is predictable from
input shape.

Examples: `git-commit`, `gh-pr-create`, `ticket-create`,
`context-audit`, `gh-pr-merge`.

### `<resource>-<noun>` → heuristic

Exploratory, multi-phase, judgment-heavy, often dispatches
subagents, may exceed 200 lines. Output depends on findings
discovered during execution.

Examples: `permission-investigator`, `memory-maintenance`,
`plugin-maintenance`.

### When in doubt — decision tree

1. **Can the agent predict the output structure before reading
   the inputs?** → verb-suffix.
2. **Does the skill dispatch ≥ 2 subagents or run ≥ 3 phases
   with branching logic?** → noun-suffix.
3. **Does the SKILL.md (or `instructions.md`) exceed the
   200-line budget?** → noun-suffix (or split the skill).
4. **Otherwise, default to verb-suffix** — bias toward the
   mechanical shape and only escalate to noun when the work
   genuinely needs exploration.

### Accepted exceptions

- `*-audit` skills (`context-audit`, `skill-audit`,
  `project-audit`) keep the verb suffix even when the body is
  multi-phase. Renaming to `-auditor` would collide with the
  agent convention (`permission-auditor`, `code-reviewer`).
- `gh-pr-doctor` uses `-doctor` as the canonical
  fix-suggesting diagnostic verb.

### Rename map (in progress)

The following skills were re-classified during the GH-217 audit:

| Current path | Renamed to | Reason |
|--------------|------------|--------|
| `skills/audit-report/` | `skills/audit-file/` | Files a ticket via fixed gh / Linear path — mechanical |
| `skills/doctor/` | `skills/plugin-doctor/` | Adds `plugin` resource prefix to match `gh-pr-doctor` |
| `skills/skill-reinforcement/` | (already renamed to `diag-friction`, see GH-214) | Skill-reinforcement was folded into the broader diag-friction skill ahead of GH-217 |

When applying a rename: `git mv skills/<old>/ skills/<new>/`,
update `name:` and `invocation-name:` in SKILL.md, grep for
cross-references across SKILL.md / agent specs / references /
rules, and keep a deprecated stub at the old path for one
release cycle.

## Family Naming

Skills use family prefixes for tab-completion discoverability:

| Directory         | Invocation name      |
|-------------------|----------------------|
| `park/`           | `Dev10x:park`            |
| `park-todo/`      | `Dev10x:park-todo`       |
| `park-remind/`    | `Dev10x:park-remind`     |
| `park-discover/`  | `Dev10x:park-discover`   |
| `session-tasks/`  | `Dev10x:session-tasks`   |
| `session-wrap-up/`| `Dev10x:session-wrap-up`  |
| `ticket-branch/`  | `Dev10x:ticket-branch`   |
| `ticket-create/`  | `Dev10x:ticket-create`   |
| `ticket-jtbd/`    | `Dev10x:ticket-jtbd`     |
| `ticket-scope/`   | `Dev10x:ticket-scope`    |

Other skills use the full directory name: `Dev10x:git-worktree`,
`Dev10x:skill-audit`, `Dev10x:skill-create`.

## `invocation-name` field

**Required on every skill.** The `invocation-name:` field makes
skills available for invocation. By default it MUST match `name:`:

```yaml
name: Dev10x:git-commit
invocation-name: Dev10x:git-commit
```

The `invocation-name:` MUST match `name:` — no exceptions. Both
fields carry the `Dev10x:` prefix for brand consistency.

## Eval Criteria Files

Eval criteria define measurable dimensions and test scenarios for skills.

**Structure:** Place all evals in `skills/<feature-name>/evals/evals.json`
- Directory name: plain feature name (no `Dev10x-` prefix)
- Filename: fixed as `evals.json` (not `Dev10x-evals.json`)
- Inside file: `skill_name` field MUST use `Dev10x:` prefix

**Schema:** See `references/eval-criteria.md` for full structure.

**Example:**
```json
{
  "skill_name": "Dev10x:git-commit",
  "eval_dimensions": [...],
  "evals": [...]
}
```

**Note:** Eval files are schema/documentation only, not code.
They do not require executable permissions or script references.

## Rationale Summary

- **Directory**: plain name → clean filesystem, no redundant prefix
- **Invocation**: `Dev10x:` prefix → branding + namespace isolation
- **`invocation-name:`**: required on every skill, matches `name:` by default
- **Families**: prefix groups for tab-completion discoverability
- **Evals**: structured JSON placed in fixed directory with prefixed `skill_name`
