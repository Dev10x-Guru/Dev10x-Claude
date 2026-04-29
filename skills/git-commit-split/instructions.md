# Split Commit Skill (Instructions)

## Overview

Split monolithic git commits into atomic, cohesive commits that follow Clean Architecture principles and dependency order. Each resulting commit should be self-contained, pass all tests, and change one well-scoped part of the code.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each phase, immediately start the next.
Never pause between phases to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Identify split points and dependency order", activeForm="Analyzing commit")`
2. `TaskCreate(subject="Start interactive rebase", activeForm="Starting rebase")`
3. `TaskCreate(subject="Create atomic commits", activeForm="Creating commits")`
4. `TaskCreate(subject="Verify history and tests", activeForm="Verifying commits")`

Set sequential dependencies: each phase blocked by the previous.

**Split strategy decision (Phase 1):** After analyzing the commit,
queue the split strategy decision in task metadata. If no other
tasks can advance, present the decision.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-split-strategy.md](./tool-calls/ask-split-strategy.md)).
Options:
- Approve split plan (Recommended) — Proceed with the proposed commit boundaries
- Adjust boundaries — I want to change how the split is organized
- Abort — Keep the original monolithic commit

## Hook Bypass Rationale (Documented Exception)

CLAUDE.md guidance states: *"Never skip hooks (`--no-verify`) or
bypass signing unless the user has explicitly asked for it."*
This skill is one of the few **documented exceptions** to that
rule, and the bypass is contained to interactive split-rebase
only.

**Why bypass is permitted here:**

- Every commit produced during a split is an **intermediate state**
  of an in-progress rebase. Pre-commit hooks that run lint,
  typecheck, or test gates routinely fail on intentionally
  incomplete intermediate states (e.g., a refactor commit that
  removes a class before the new-feature commit adds its
  replacement).
- Forcing hooks at every intermediate commit would either block
  the split entirely or push authors toward worse workarounds
  (combining commits to satisfy hooks, defeating the skill's
  purpose).
- Hooks **are** enforced after the rebase completes — Step 8 runs
  `git rebase --exec "pre-commit run --all-files" develop`, which
  re-validates every commit against the full project state.

**Scope of this exception:**

- ✅ Inside `git rebase -i` workflow described below — `--no-verify`
  used during incremental commit creation, with the rebase exec
  step running hooks at the end.
- ❌ Routine standalone commits — MUST use the
  `Dev10x:git-commit` skill, which never bypasses hooks.
- ❌ Force pushes, signing bypass, or other guardrails — out of
  scope for this skill.

Each `git commit --no-verify` in the examples below is annotated
with a `cli-friction:` comment naming this rationale. If you
copy a snippet outside the rebase workflow, drop the
`--no-verify` flag — the bypass justification does not travel.

## Core Principles

### Atomic Commits

- **Self-contained**: Each commit must be complete and independent
- **Working code**: Each commit must pass tests and linters
- **One logical change**: Even a single-character change can be a commit if it's logically separate
- **Same file/line OK**: Multiple commits may touch the same file or line if they're logically distinct

### Why This Matters

- Makes `git blame` useful for understanding why code exists
- Enables `git bisect` for debugging (only works if every commit is working code)
- Makes `git revert` and `git cherry-pick` practical
- Simplifies code review by allowing commit-by-commit review
- Documents the thinking process and evolution of the solution

### Feature Cohesion Over File Type

**Bad: Grouping by file type**
```
Commit 1: Add all DTOs
Commit 2: Add all repositories
Commit 3: Add all services
```

**Good: Grouping by feature**
```
Commit 1: Add batch repository method (implementation + tests)
Commit 2: Add type safety change needed by refactoring
Commit 3: Add calculator + refactor existing code to use it
Commit 4: Add new service with its DTOs and fakers
```

**Key insight**: DTOs, fakers, and other supporting code should be committed with the feature that uses them, not grouped separately by type.

## Dependency Order

Always split commits following architectural layers and dependency order:

1. **Utilities** - Low-level helpers (e.g., `as_dict` decorator)
2. **Data access** - Repository methods, database queries
3. **Type safety** - DTO changes needed by following commits
4. **Refactoring** - Extract existing code, eliminate N+1 queries
5. **New features** - New services, calculators (with their DTOs)
6. **API layer** - GraphQL/REST endpoints, presentation

## When to Use This Skill

Use this skill when:
- A commit contains multiple logically distinct changes
- A commit mixes refactoring with new features
- A commit has poor cohesion (unrelated changes bundled together)
- Reviewers request the commit be split for easier review
- A feature commit includes infrastructure changes that should be separate
- DTOs are grouped separately from the code that uses them

## Interactive Rebase Workflow

### Step 1: Analyze the Commit

**Check what the commit contains:**

```bash
# View commit summary
git show --stat COMMIT_HASH

# View full diff
git show COMMIT_HASH

# Check which files changed
git show --name-status COMMIT_HASH
```

**Identify logical boundaries:**
- Are there utility functions that other changes depend on?
- Are there database/repository changes separate from business logic?
- Is there refactoring mixed with new features?
- Are DTOs defined separately from the code using them?
- Is there type safety work needed by following changes?

**Map dependencies:**
- What needs to come first? (utilities, data access)
- What depends on what? (refactoring needs type changes)
- What comes last? (API layer, new features)

### Step 2: Start Interactive Rebase

**From develop (or main branch):**

```bash
# Start interactive rebase, marking commit for editing
GIT_SEQUENCE_EDITOR="sed -i 's/^pick COMMIT_HASH/edit COMMIT_HASH/'" git rebase -i develop
```

**Reset the commit to unstage all changes:**

```bash
git reset HEAD~1
```

**Check status:**

```bash
git status  # See all unstaged changes
git diff --stat  # See what changed
```

### Step 3: Create First Atomic Commit

**Stage only the files for the first logical change:**

```bash
# Stage specific files
git add path/to/file1.py path/to/file2.py

# Or stage parts of files interactively
git add -p path/to/file.py
```

**Commit with proper message format:**

Use the Dev10x:git-commit skill conventions:
- Gitmoji prefix (new feature, refactor, bug, etc.)
- Ticket ID from branch name
- Concise description
- 72 character limit for title

```bash
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
TICKET-ID Brief description of first change

Detailed explanation of what this change does and why.

EOF
)"
```

**Note on `--no-verify`**: This flag is used **only** because each
intermediate commit may not satisfy lint/typecheck hooks during
split-rebase. See the "Hook Bypass Rationale" section above for
the full justification. Step 8 re-runs all hooks via
`git rebase --exec` once the rebase completes, so the final
branch state is hook-clean.

### Step 4: Create Subsequent Commits

**Repeat for each logical change:**

```bash
# Stage next set of changes
git add files_for_next_change...

# Commit
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
TICKET-ID Next logical change

Description...

EOF
)"
```

**Follow dependency order:**
1. Utilities first
2. Data access layer
3. Type safety improvements
4. Refactoring
5. New features (with their DTOs/fakers)
6. API layer last

### Step 5: Handle Complex Scenarios

#### Scenario A: DTOs Used by Multiple Commits

**Problem**: DTOs defined in one place but used by different commits.

**Solution**: Move DTOs to the commit that primarily uses them.

**Example**:
```bash
# If PendingReturnOrder DTO is only used by PendingReturnOrderService
# Include the DTO in the same commit as the service

# Commit 4: Refactoring (uses WorkOrderNo type)
git add dto.py  # Only the type change line
git commit --no-verify -m "TICKET-ID Improve type safety..."  # cli-friction: allow no-verify — split-rebase example

# Commit 5: New service (uses ServiceItemQuantity, PendingReturnOrder)
git add dto.py  # The new DTO classes
git add main.py  # The service implementation
git add tests/fakers.py  # Fakers for the DTOs
git add tests/test_main.py  # Tests for the service
git commit --no-verify -m "TICKET-ID Add new service..."  # cli-friction: allow no-verify — split-rebase example
```

#### Scenario B: Separating Refactoring from New Features

**Problem**: One commit contains both refactoring of existing code and new feature code.

**Solution**: Split into two commits - refactoring first, then new feature.

**Example**:
```bash
# Commit: Refactoring
# - Add RemainingQuantityCalculator
# - Refactor RefundCalculator to use it
# - Update existing tests

# Commit: New Feature
# - Add PendingReturnOrderService
# - Add its DTOs and fakers
# - Add its tests
```

#### Scenario C: Shared File Modified by Multiple Commits

**Problem**: Same file (e.g., `main.py`) needs changes in multiple commits.

**Solution**: Edit the file incrementally for each commit.

**Strategy**:
1. Reset to get full diff
2. Stage file for first commit
3. Edit file to remove changes not needed yet
4. Commit
5. Edit file again to add back next set of changes
6. Stage and commit
7. Repeat

**Example workflow**:
```bash
# Get full changes
git reset HEAD~1

# For first commit (refactoring only)
git add main.py tests/test_main.py

# Edit main.py to remove PendingReturnOrderService class
# Edit imports to remove PendingReturnOrder, ServiceItemQuantity

git commit --no-verify -m "TICKET-ID Refactoring..."  # cli-friction: allow no-verify — split-rebase example

# For second commit (new service)
# Edit main.py to add back PendingReturnOrderService class
# Edit imports to add back the DTOs

git add main.py dto.py tests/fakers.py tests/test_main.py
git commit --no-verify -m "TICKET-ID Add new service..."  # cli-friction: allow no-verify — split-rebase example
```

### Step 6: Continue Rebase

**After creating all atomic commits:**

```bash
git rebase --continue
```

**If conflicts occur:**
```bash
# Resolve conflicts
git status  # See conflicting files
# Edit files to resolve
git add resolved_files...
git rebase --continue
```

### Step 7: Verify Each Commit

**Run tests for each commit:**

```bash
# Check each commit individually
for commit in $(git log --reverse --format=%H develop..HEAD); do
  echo "=== Testing $commit ==="
  git checkout $commit
  Skill(Dev10x:py-test path/to/tests/)
  if [ $? -ne 0 ]; then
    echo "Tests failed at $commit"
    break
  fi
done

# Return to branch HEAD
git checkout HEAD
```

**If a commit fails tests:**
1. Use `git rebase -i develop` to edit the failing commit
2. Fix the issue
3. Amend: `git commit --amend --no-verify`
4. Continue: `git rebase --continue`

### Step 8: Final Verification

**Check commit structure:**

```bash
# View all commits
git log --oneline develop..HEAD

# View each commit's changes
git log -p develop..HEAD
```

**Run full test suite:**

```bash
Skill(Dev10x:py-test path/to/tests/)
```

**Run linters if skipped during split:**

```bash
# Run pre-commit hooks on all commits
git rebase --exec "pre-commit run --all-files" develop
```

## Commit Message Format

Follow the Dev10x:git-commit skill conventions:

**Structure:**
```
<gitmoji> <TICKET-ID> <description>

<detailed explanation>

<additional context if needed>
```

**Gitmoji mapping:**
- ✨ (`:sparkles:`) - New feature
- ♻️ (`:recycle:`) - Refactoring
- 🐛 (`:bug:`) - Bug fix
- ✅ (`:white_check_mark:`) - Tests
- ⚡ (`:zap:`) - Performance
- 🔒 (`:lock:`) - Security

**Important rules:**
- Title <= 72 characters
- One space after gitmoji, one space after ticket ID
- No "Co-Authored-By: Claude" footer
- Use heredoc for multi-line messages to preserve formatting

**Examples:**
```
✨ PAY-314 Add as_dict decorator to collections module
♻️ PAY-314 Add RemainingQuantityCalculator and refactor
✨ PAY-314 Add PendingReturnOrderService
```

## Common Patterns

### Pattern 1: Utility -> Feature -> API

**Typical split:**
1. Add utility function (e.g., `as_dict` decorator)
2. Add data access method (e.g., `get_returns_qty_batch`)
3. Add type safety (e.g., `order_no: WorkOrderNo`)
4. Add calculator/refactor (e.g., `RemainingQuantityCalculator`)
5. Add new service with DTOs (e.g., `PendingReturnOrderService`)
6. Expose via API (e.g., GraphQL query)

### Pattern 2: Refactoring Existing + Adding New

**When you have:**
- Refactoring of existing code (e.g., eliminate N+1 queries)
- New feature code (e.g., new service)

**Split into:**
1. Commit: Refactoring with performance improvements
2. Commit: New feature that uses the refactored code

### Pattern 3: Type Safety Improvements

**When type changes enable following work:**
1. Commit: Type safety change (e.g., `str` -> `WorkOrderNo`)
2. Commit: Code that uses the stronger typing

## Tips for Success

### Do's

- **Commit in dependency order** - Always ask "what depends on what?"
- **Keep related changes together** - DTOs with the service that uses them
- **Test after each commit** - Ensure each commit produces working code
- **Use clear commit messages** - Future you will thank you
- **Follow gitmoji conventions** - Consistent with project standards

### Don'ts

- **Don't group by file type** - Group by feature cohesion instead
- **Don't skip testing** - Every commit must pass tests
- **Don't mix refactoring and new features** - Separate concerns
- **Don't create commits with broken code** - Each commit must work
- **Don't forget dependency order** - Utilities before features

## Troubleshooting

### "Too many commits"

**Problem**: Split resulted in 10+ small commits.

**Solution**: This is often fine! If each commit is logically distinct and follows dependency order, having many commits is better than having few large commits.

**Guidelines**:
- 5-7 commits is typical for a medium feature
- 10-20 commits is acceptable if they're meaningful
- Consider combining only if commits are too granular (e.g., fixing typos)

### "Commits don't pass tests individually"

**Problem**: Tests pass at HEAD but fail at intermediate commits.

**Solution**: Fix each commit to be independently testable:
1. Identify which commit fails
2. Rebase to edit that commit: `git rebase -i develop`
3. Add missing changes to make tests pass
4. Amend and continue

### "Conflicts during rebase"

**Problem**: Conflicts when continuing rebase.

**Solution**:
1. Resolve conflicts in files
2. Stage resolved files: `git add file.py`
3. Continue: `git rebase --continue`
4. If unsure, abort and restart: `git rebase --abort`

### "DTOs in wrong commit"

**Problem**: Realized DTOs should be in a different commit.

**Solution**: Use interactive rebase to reorganize:
1. Start rebase: `git rebase -i develop`
2. Mark commits for editing: Change `pick` -> `edit`
3. Rearrange files between commits
4. Continue until correct

## Example Session

See `references/split-commit-example.md` for a complete real-world example of splitting a commit with:
- Utility function extraction
- Repository batch method addition
- Type safety improvements
- Refactoring with performance gains
- New service with DTOs
- API layer changes

## Integration with Other Skills

```
Dev10x:git-commit-split
├── Uses: Dev10x:git-commit (for message formatting)
├── Output: Multiple atomic commits
└── Followed by: Dev10x:gh-pr-create
```

## Success Criteria

After splitting, commits should:

- Follow dependency order (utilities -> data -> refactoring -> features -> API)
- Each commit passes all tests independently
- Related changes grouped by cohesion (DTOs with services that use them)
- Clear separation between refactoring and new features
- Proper gitmoji and ticket references
- Commit messages <= 72 characters
- Each commit is self-contained and reviewable independently
