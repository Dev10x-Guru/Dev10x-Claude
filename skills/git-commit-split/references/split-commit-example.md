# Real-World Example: Splitting PAY-314 Commit

This document shows a complete real-world example of splitting a monolithic commit into atomic commits following the principles in the split-commit skill.

## Note on `--no-verify` in this example

The `git commit --no-verify` invocations in the snippets below
are **scoped to the interactive split-rebase workflow** and are
the documented exception to CLAUDE.md's general "never skip
hooks" rule. See `instructions.md` § "Hook Bypass Rationale" for
the full justification. The exception only covers intermediate
commits during an active `git rebase -i`; hooks run via
`git rebase --exec "pre-commit run --all-files"` once the
rebase completes. Do **not** copy these snippets into routine
commit flows — use the `Dev10x:git-commit` skill instead, which
respects hooks.

## Original Commit

**Commit:** `01b5189e Return remaining item qty with pending return order`

**Files changed:** 10 files, 442 insertions(+), 65 deletions(-)

**Problems:**
- Mixed utilities, data access, DTOs, refactoring, new features, and API changes
- DTOs grouped separately from the code using them
- Refactoring mixed with new feature
- Hard to review as a single commit

## Analysis Phase

**Identified logical boundaries:**
1. **Utility function** - `as_dict` decorator in `collections.py`
2. **Data access** - `get_returns_qty_batch()` batch repository method
3. **DTOs** - Type safety + new DTOs (initially grouped, needs splitting)
4. **Refactoring** - `RemainingQuantityCalculator` + refactor existing `RefundCalculator`
5. **New feature** - `PendingReturnOrderService`
6. **API layer** - GraphQL query updates

**Dependency mapping:**
- Utility (`as_dict`) → used by calculator
- Batch method → used by calculator
- Type safety (`WorkOrderNo`) → used by refactoring
- Calculator → used by both refactoring and new service
- New service DTOs → only used by new service
- API → uses new service

## Split Strategy

Based on analysis, split into 5 atomic commits following dependency order:

1. Add `as_dict` utility decorator
2. Add batch repository method with tests
3. Add calculator and refactor existing code (WITH WorkOrderNo type change)
4. Add new service with its DTOs and fakers
5. Expose via GraphQL API

**Key insight:** DTOs belong in the commit that uses them, not as standalone commits.

## Interactive Rebase Process

### Step 1: Start Rebase

```bash
# Mark commit for editing
GIT_SEQUENCE_EDITOR="sed -i 's/^pick 01b5189e/edit 01b5189e/'" git rebase -i develop

# Reset to unstage all changes
git reset HEAD~1

# Verify status
git status
```

**Result:** All changes unstaged, ready to commit incrementally.

### Step 2: Commit 1 - Utility Function

**Stage only collections.py:**

```bash
git add src/app/collections.py
```

**Review changes:**
- Added `K = TypeVar("K")` type variable
- Added `as_dict()` decorator function

**Commit:**

```bash
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
✨ PAY-314 Add as_dict decorator to collections module

Add as_dict decorator that converts iterator of tuples to dict,
mirroring the existing as_tuple decorator pattern.
EOF
)"
```

**Stats:** 1 file, 10 insertions

### Step 3: Commit 2 - Batch Repository Method

**Stage repository files:**

```bash
git add src/app_pos/orders/returns/repository.py \
        src/app_pos/orders/returns/tests/test_repository.py
```

**Review changes:**
- Added `get_returns_qty_batch()` method to repository
- Added `TestReturnOrderRepositoryGetReturnsQtyBatch` test class with 5 test methods
- Tests cover: batch retrieval, empty input, summing across orders

**Commit:**

```bash
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
✨ PAY-314 Add batch method for retrieving return quantities

Add ReturnOrderRepository.get_returns_qty_batch() for efficient
retrieval of return quantities across multiple service items in a
single operation, eliminating N+1 query problems.
EOF
)"
```

**Stats:** 2 files, 128 insertions, 3 deletions

### Step 4: Commit 3 - Refactoring with Type Safety

**Challenge:** The `main.py` file contains both refactoring (RemainingQuantityCalculator) and new feature (PendingReturnOrderService). Need to split a single file across multiple commits. Additionally, the refactoring needs the `WorkOrderNo` type change in `dto.py`.

**Key insight:** Include the `WorkOrderNo` type change in THIS commit because the refactoring uses it. Don't create a standalone type safety commit that provides no value to reviewers.

**Solution:** Edit the file to include only refactoring parts, plus the DTO type change that the refactoring needs.

**Steps:**
1. Restore full `main.py` from git diff
2. Edit `main.py` to remove `PendingReturnOrderService` class
3. Edit imports to remove `PendingReturnOrder`, `ServiceItemQuantity`
4. Save `test_main.py` with only refactoring tests (first 432 lines)
5. Remove imports for `PendingReturnOrder`, `PendingReturnOrderService`, `WorkOrderFaker`
6. Stage dto.py with only the WorkOrderNo type change (not the new DTO classes)

**Stage:**

```bash
git add src/app_pos/orders/returns/dto.py \
        src/app_pos/orders/returns/main.py \
        src/app_pos/orders/returns/tests/test_main.py
```

**Review changes:**
- **dto.py:** Changed `order_no: str` → `order_no: WorkOrderNo` (type safety for refactoring)
- **main.py:** Added `RemainingQuantityCalculator` class
- **main.py:** Refactored `ReturnOrderRefundCalculator` to use batch calculator
- **test_main.py:** Updated `TestServiceItemRefundCalculator` fixtures to stub calculator
- **test_main.py:** Updated `TestReturnOrderRefundCalculator` to stub calculator

**Commit:**

```bash
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
♻️ PAY-314 Add RemainingQuantityCalculator and refactor

Add RemainingQuantityCalculator to compute returnable quantities
using batch loading. Change ReturnOrder.order_no from str to
WorkOrderNo for type safety. Refactor ReturnOrderRefundCalculator
to use the batch calculator, eliminating N+1 query problems and
reducing database queries from 101 to 3 for 50 items (97%).
EOF
)"
```

**Stats:** 3 files, 99 insertions, 26 deletions

**Note:** Used ♻️ (refactor) gitmoji, not ✨ (feature), because this refactors existing code. The WorkOrderNo type change is included here because this refactoring uses it.

### Step 5: Commit 4 - New Feature with DTOs

**Key insight:** This is where DTOs belong - with the feature that uses them! Not in a separate "DTOs commit".

**Restore full files and stage:**

```bash
# Restore full main.py with PendingReturnOrderService
git show e5571b45:src/app_pos/orders/returns/main.py > src/app_pos/orders/returns/main.py

# Add new DTO classes to dto.py
# (ServiceItemQuantity and PendingReturnOrder)

# Create fakers for the new DTOs
```

**Stage all feature files:**

```bash
git add src/app_pos/orders/returns/dto.py \
        src/app_pos/orders/returns/main.py \
        src/app_pos/orders/returns/tests/fakers.py \
        src/app_pos/orders/returns/tests/test_main.py
```

**Review changes:**
- Added `ServiceItemQuantity` DTO (only used by this service)
- Added `PendingReturnOrder` DTO (only used by this service)
- Added `ServiceItemQuantityFaker` and `PendingReturnOrderFaker`
- Added `PendingReturnOrderService` class
- Added `TestPendingReturnOrderService` test class

**Commit:**

```bash
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
✨ PAY-314 Add PendingReturnOrderService

Add PendingReturnOrderService to aggregate work order services
with remaining quantities for each service item, enabling clients
to retrieve all items that can still be returned.
EOF
)"
```

**Stats:** 4 files, 147 insertions

**Note:** Used ✨ (feature) gitmoji because this adds new functionality.

### Step 6: Commit 5 - API Layer

**Stage API files:**

```bash
git add src/app_pos/orders/returns/api/dto.py \
        src/app_pos/orders/returns/api/queries.py \
        src/app_pos/orders/returns/api/tests/test_queries.py
```

**Review changes:**
- Added `GServiceItemQuantity` and `GPendingReturnOrder` GraphQL types
- Updated `GetPendingReturnOrderQuery` to use new service
- Updated tests to use service instead of repository

**Commit:**

```bash
git commit --no-verify -m "$(cat <<'EOF'  # cli-friction: allow no-verify — split-rebase example, hooks re-run after final commit
✨ PAY-314 Expose remaining quantities via GraphQL API

Update GetPendingReturnOrderQuery to return pending return order
with remaining quantities for each service item, enabling clients
to know how much of each item is available for return.
EOF
)"
```

**Stats:** 3 files, 58 insertions, 36 deletions

### Step 7: Continue Rebase

```bash
git rebase --continue
```

**Result:** Successfully rebased and updated branch.

## Final Commit Structure

```
47d21012 ✨ PAY-314 Expose remaining quantities via GraphQL API
8b814aaa ✨ PAY-314 Add PendingReturnOrderService
692f2e1f ♻️ PAY-314 Add RemainingQuantityCalculator and refactor
3bb6dacf ✨ PAY-314 Add batch method for retrieving return quantities
b2038670 ✨ PAY-314 Add as_dict decorator to collections module
```

**Note:** This is the actual final structure with 5 commits. The WorkOrderNo type change is included in commit 692f2e1f (refactoring) where it's actually used, not as a standalone commit.

## Verification

**Run tests for all commits:**

```bash
Skill(Dev10x:py-test src/app_pos/orders/returns/tests/ -v)
```

**Result:** 118 passed, all tests passing

**Check each commit individually:**

```bash
for commit in $(git log --reverse --format=%H develop..HEAD); do
  git checkout $commit
  Skill(Dev10x:py-test src/app_pos/orders/returns/tests/)
done
```

**Result:** All commits pass tests independently

## Key Lessons Learned

### 1. DTOs Belong With Code That Uses Them

**Wrong approach (initial attempt):**
- Commit 2: Add all DTOs together (ServiceItemQuantity + PendingReturnOrder + WorkOrderNo type change)
- Commit 3: Refactoring that uses WorkOrderNo
- Commit 4: Service that uses ServiceItemQuantity and PendingReturnOrder

**Right approach (final):**
- Commit 3: Refactoring WITH WorkOrderNo type change
- Commit 4: Service WITH ServiceItemQuantity and PendingReturnOrder DTOs

**Critical lesson:** Never create standalone DTO commits. A DTO by itself provides no value to reviewers. They would have to jump between commits to understand if the DTO is actually used or just YAGNI. Include DTO changes in the commit that uses them.

### 2. Separate Refactoring from Features

**Challenge:** Same file contained both refactoring and new feature.

**Solution:**
- Commit 3: Refactoring of existing code (♻️ recycle emoji)
- Commit 4: New feature code (✨ sparkles emoji)

**Lesson:** Even when touching the same file, separate refactoring (improving existing code) from features (adding new code). Use different gitmojis to signal the purpose.

### 3. Dependency Order Matters

**Order followed:**
1. Utilities (as_dict) - lowest level
2. Data access (batch method) - infrastructure
3. Refactoring (calculator + WorkOrderNo type change) - uses utilities and batch method
4. Features (new service + its DTOs) - uses calculator
5. API (GraphQL) - uses service

**Lesson:** Always commit in dependency order so each commit builds on previous ones. Include supporting changes (like type safety improvements) in the commit that uses them, not as separate commits.

### 4. Same File, Multiple Commits Is OK

**File:** `main.py` modified in commits 3 and 4 (refactoring vs. new feature)
**File:** `dto.py` modified in commits 3 and 4 (type change for refactoring vs. new DTOs for service)

**Lesson:** Don't be afraid to split changes to the same file across multiple commits if they're logically distinct. Same file, different logical changes = different commits.

### 5. Test Each Commit

**Verification at each step:**
- Staged correct files
- Ran tests before committing
- Verified tests pass after commit
- Final verification across all commits

**Lesson:** Every commit must produce working, tested code.

## Common Mistakes to Avoid

### Mistake 1: Creating Standalone DTO Commits

**Bad:**
```
Commit 2: Add all DTOs
- ServiceItemQuantity
- PendingReturnOrder
- WorkOrderNo type change

Commit 3: Add refactoring that uses WorkOrderNo

Commit 4: Add service that uses ServiceItemQuantity and PendingReturnOrder
```

**Problem:** Reviewers must jump between commits to see if DTOs are used or just YAGNI. Standalone DTO commits provide no value.

**Good:**
```
Commit 3: Refactoring WITH WorkOrderNo type change
- RemainingQuantityCalculator
- ReturnOrder.order_no type change
- Refactor existing code

Commit 4: Service WITH its DTOs
- PendingReturnOrder
- ServiceItemQuantity
- PendingReturnOrderService
- Fakers and tests
```

**Solution:** Include DTOs in the commit that uses them. Reviewers can see intent and usage together.

### Mistake 2: Mixing Refactoring and New Features

**Bad:**
```
Commit: Add calculator and service together
- RemainingQuantityCalculator
- Refactor ReturnOrderRefundCalculator
- PendingReturnOrderService (new feature)
- All mixed together
```

**Problem:** Combining refactoring with new features makes commits harder to review and harder to revert if issues arise.

**Good:**
```
Commit 3: Refactoring only
- RemainingQuantityCalculator
- Refactor ReturnOrderRefundCalculator to use it
- WorkOrderNo type change needed by refactoring

Commit 4: New feature only
- PendingReturnOrderService
- DTOs for the service
- Fakers and tests
```

**Solution:** Separate refactoring (♻️) from new features (✨). Each commit has a single, clear purpose.

### Mistake 3: Ignoring Dependencies

**Bad order:**
```
1. Add API (needs service)
2. Add service (needs calculator)
3. Add calculator (needs batch method)
4. Add batch method
```

**Good order:**
```
1. Add batch method
2. Add calculator
3. Add service
4. Add API
```

## Time Investment

**Total time:** ~45 minutes

**Breakdown:**
- Analysis: 5 minutes
- Planning split strategy: 5 minutes
- Interactive rebase and commits: 25 minutes
- Fixing DTO placement: 5 minutes
- Testing and verification: 5 minutes

**Value:**
- Makes code review 10x easier
- Documents evolution of solution
- Each commit is independently revertable
- Enables bisecting if bugs found later
- Shows clear thinking process

## Conclusion

Splitting commits properly takes practice but pays dividends in code review, debugging, and understanding. The key principles are:

1. **Follow dependency order** - Utilities → Data → Refactoring (with types it needs) → Features (with their DTOs) → API
2. **Group by cohesion** - DTOs with features that use them, not by file type
3. **Separate concerns** - Refactoring vs new features get separate commits
4. **Test everything** - Each commit must pass all tests independently
5. **Think in layers** - Clean Architecture guides the split, but pragmatically include supporting changes (DTOs, type changes) in the commit that uses them

**Most important:** Never create standalone DTO or type safety commits. Include them in the commit that uses them so reviewers can understand intent and usage together.

This example shows that even complex commits spanning 10 files can be split into clean, atomic commits that tell a story and make review easy.
