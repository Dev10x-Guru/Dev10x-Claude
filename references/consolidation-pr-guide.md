# Consolidation PR Guide

Patterns and guidance for pull requests that bundle multiple features,
directories, or components into a single merge.

## When Consolidation is Appropriate

Consolidation PRs combine multiple logical units into one PR when:

- **Plugin/directory merges**: Combining separate plugin directories into a unified plugin
  (e.g., 11 separate plugins → 1 unified Dev10x plugin)
- **Directory restructuring**: Moving files across multiple directories with no logic changes
- **Dependency upgrades**: Updating multiple packages atomically for compatibility
- **Infrastructure refactors**: Restructuring code organization without behavioral changes

Do **not** use consolidation for unrelated features — keep feature PRs separate
so reviewers can evaluate each feature independently.

## PR Body for Consolidation

The JTBD Job Story must capture the **consolidation outcome**, not individual features.

**Example JTBD for consolidation**:
```markdown
**When** managing 11 separate plugin directories, **the maintainer wants to**
unify them into a single Dev10x plugin, **so the maintainer can** simplify
distribution and reduce maintenance overhead.
```

Not:
```markdown
**When** shipping a feature, **the maintainer wants to** add feature X, **so the maintainer can** enable Y.
```

The consolidation outcome is the "why" — the individual features/fixes are supporting details.

## Commit Structure for Consolidation

In consolidation PRs, commit messages should reflect the consolidation scope,
not individual directory moves.

**Example**:
```
🤖 DEV-4 Consolidate 11 plugins into unified Dev10x
```

Not:
```
✨ Add git-worktree plugin
✨ Add gh-pr-create plugin
✨ Add git-commit plugin
... (11 more)
```

**Why?** Consolidation is a single logical change (structure); individual
plugins are implementation details. The main commit describes the outcome;
subsequent commits (if any) describe optional supporting changes.

## Code-Level Consolidations

Code consolidations differ from structural consolidations:

- **Structural** (e.g., plugin merges): Move entire directories,
  preserve file structure, verify all components load
- **Code-level** (e.g., deduplication): Remove duplicate implementations,
  consolidate to canonical source, verify all call sites updated

For code-level consolidations, review focuses on:
1. No duplicate implementations remain in any location
2. All call sites reference the canonical version
3. Test coverage follows the new import location
4. No orphaned imports, stale references, or unused modules

## Reviewers' Expectations

Consolidation PRs are typically large (hundreds of files). Reviewers expect:

1. **Atomic move**: Files are moved with `git mv`, preserving history
2. **No logic changes**: Consolidation doesn't alter behavior
3. **Comprehensive**: All pieces of each component are included
4. **Validation**: Author has verified integrated functionality

Reviewers will **not** read every file — they verify:
- No files are duplicated or lost
- Paths are updated correctly in references
- No unrelated logic changes snuck in

## Example Structure

```
📁 Before:
plugins/git-worktree/
plugins/gh-pr-create/
plugins/git-commit/
... (8 more)

📁 After (single PR):
dev10x/
  ├── skills/
  ├── hooks/
  ├── commands/
  └── agents/
```

**PR body**:
```markdown
**When** managing 11 separate plugin directories, **the maintainer wants to**
consolidate them into a single Dev10x plugin, **so the maintainer can** reduce
distribution complexity and improve maintainability.

[Brief summary of changes]

Fixes: https://github.com/Dev10x-Guru/dev10x-claude/issues/...
```

## Testing Consolidation PRs

After consolidation:

- Verify all skills load correctly
- Check that paths in SKILL.md, references, and hooks still resolve
- Validate that no plugin functionality is broken
- Test CLI invocation across consolidated namespace

## Anti-Patterns

- ❌ Consolidating **and** refactoring logic in the same PR — split them
- ❌ Consolidating unrelated plugins — keep feature PRs separate
- ❌ Hiding bug fixes inside consolidation — separate and cite
- ❌ Assuming reviewers understand scope — make JTBD explicit
