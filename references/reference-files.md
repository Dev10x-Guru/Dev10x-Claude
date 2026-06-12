# Reference File Discoverability & Maintenance

Guidelines for adding and maintaining reference files in the `references/` directory.

## What is a Reference File?

Reference files are detailed guidance documents stored in `references/` that:
- Provide operational details beyond rules (see `.claude/rules/`)
- Are loaded on-demand by skills, agents, or CI workflows
- Are listed in `.claude/rules/INDEX.md` for discoverability
- Can be cross-referenced by multiple consumers

Examples: `git-commits.md`, `git-pr.md`, `execution-modes.md`, `friction-levels.md`.

## Adding a New Reference File

When creating a new reference file, always follow this checklist:

### 1. Create the File

- Save in `references/` directory with descriptive name (e.g., `reference-files.md`)
- Use Markdown format
- Keep under 200 lines (hard budget; see `references/task-orchestration.md` for overflow justification pattern)
- Include a title (H1) and one-line description at the top

### 2. Update `.claude/rules/INDEX.md`

Add an entry to the **Reference Documents table** (lines 67-96):
- Use alphabetical order by filename
- Include three columns: `File`, `Topic`, `Loaded by`, `Scope`
- Example:
  ```markdown
  | `reference-files.md` | Reference file discoverability | `reviewer-rules-maintenance` | Always loaded |
  ```

### 3. Update `.claude/rules/INDEX.md` § File Patterns -> Agents

If the reference file is loaded conditionally by agents, update:
- The **File Patterns -> Agents -> References** table (lines 26-40) to list the new file under "Required References"
- The **Loading Strategy** table (lines 42-50) with loading conditions

### 4. Document Scope & Consumers

In your reference file header, add comments identifying:
- What workflows/agents load it (`Loaded by: ...`)
- When it's used (`When: ...`)
- Example:
  ```markdown
  # Reference File Example

  **Loaded by**: `reviewer-skill-behavior.md`, `work-on` skill
  **When**: Reviewing skills with playbooks; during playbook execution
  ```

## Well-Formed Entry Example

**In INDEX.md:**
```markdown
| `execution-modes.md` | Execution modes (solo/team/pair) & precedence | `skill-audit` skill, `work-on` skill | Referenced, loaded on-demand |
```

## Anti-Patterns

- ❌ Creating a reference file but forgetting to list it in INDEX.md
  - Symptom: Reviewers flag it as missing
  - Impact: New file is undiscoverable via INDEX.md
- ❌ Adding to a reference file's scope without updating INDEX.md
  - Symptom: Agent expects file to load but it's not listed in Loading Strategy
  - Impact: Agent misses required content
- ❌ Creating a reference file that duplicates guidance in `.claude/rules/`
  - Symptom: Same concept appears in two places with different wording
  - Impact: Maintenance burden; confused guidance
  - Solution: Prefer rules for mandatory process; use references for detailed examples

## Maintenance

When updating a reference file:
- Check if INDEX.md scope or consumers changed
- Update INDEX.md entry if loading conditions changed
- If adding to scope, verify consumers are prepared to use it

## Cross-Reference

See `.claude/rules/INDEX.md` § Directory Contract for the distinction between rules and references.
