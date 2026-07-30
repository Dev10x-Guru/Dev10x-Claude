# Technical Task Scoping Template

Use this template for technical improvements, refactoring, or infrastructure work that doesn't directly provide business value.

---

# [Technical Task Title]

## Objective
[What we're building/refactoring and why from a technical perspective]

Example:
"Refactor payment repository to extend BaseRepository, extracting common CRUD operations to reduce code duplication and establish consistent repository patterns across the codebase."

## Technical Approach
[High-level technical solution]

Example:
"Create a generic BaseRepository with CRUD methods, update PaymentRepository to extend it, remove duplicated methods, ensure all tests still pass with no breaking changes."

---

## Architecture

**Components:**

**Repositories:**
- Modify: `BaseRepository` - Add generic CRUD methods
- Refactor: `PaymentRepository` - Extend BaseRepository
- Refactor: `TransactionRepository` - Extend BaseRepository (future)

**Services:**
- No changes needed

**DTOs:**
- No changes needed

**Models:**
- No changes needed

**Database Changes:**
- None

**GraphQL Changes:**
- None

---

## Entities

[Data shapes introduced or modified by this change. For pure
refactors, the entities are usually class hierarchies / interfaces,
not database tables. List them anyway — downstream tooling
(`Dev10x:spec-sync`) uses this section to detect structural drift.]

**New / changed types:**

| Type | Properties / Methods | Relationships |
|------|---------------------|---------------|
| `BaseRepository[T]` | `get`, `list`, `create`, `update`, `delete` (generic) | Parent of `PaymentRepository`, `TransactionRepository` |
| `PaymentRepository` | Custom: `get_by_order_no` | Now extends `BaseRepository[PaymentDto]` |

For refactors with no entity changes, write `No new entities; type
parameter `T` of `BaseRepository` is the only new generic.`

---

## Implementation Steps

1. **Update BaseRepository with Generic CRUD**
   - File: `src/app/repositories/base.py`
   - Add methods:
     - `get(id: int) -> DTO`
     - `list(filters: dict) -> List[DTO]`
     - `create(dto: DTO) -> DTO`
     - `update(id: int, dto: DTO) -> DTO`
     - `delete(id: int) -> None`
   - Pattern: Use generics (`Generic[T]`) with type parameter
   - Reference: Django's generic views for inspiration on generic patterns

2. **Refactor PaymentRepository to Extend BaseRepository**
   - File: `src/payments/repository.py`
   - Change: `class PaymentRepository(BaseRepository[PaymentDto])`
   - Remove: Duplicate CRUD methods
   - Keep: Custom payment-specific queries (`get_by_order_no`, etc.)
   - Verify: All existing method signatures unchanged

3. **Update DI Container** (if needed)
   - File: `src/app/container/__init__.py`
   - Check: BaseRepository registration
   - Verify: PaymentRepository still works with injection

4. **Update Tests**
   - File: `src/payments/tests/test_repository.py`
   - Verify: All existing tests pass
   - Add: Tests for base methods if needed
   - Pattern: No new tests needed if behavior unchanged

5. **Run Full Test Suite**
   - Command: `Skill(Dev10x:py-test src/payments/tests/)`
   - Verify: 100% passing
   - Check: Coverage maintained

6. **Code Review Preparation**
   - Document: What changed and why
   - Ensure: No breaking changes
   - List: Benefits (reduced duplication, consistency)

---

## Code References
- `src/app/repositories/base.py` - Base class to extend
- `src/payments/repository.py:PaymentRepository` - Class to refactor
- `src/quotes/repository.py:WorkOrderRepository` - Similar pattern example
- `src/payments/tests/test_repository.py` - Tests to maintain

---

## Dependencies

**Depends on:**
- None

**Related to:**
- PAY-275: "Establish repository base class" (parent epic)
- PAY-281: "Refactor QuoteRepository" (similar future work)

**Blocks:**
- None

---

## Technical Risks

**Risk: Breaking existing repository behavior**
- **Scenario:** Generic methods don't handle edge cases correctly
- **Mitigation:**
  - Run full test suite before and after
  - Keep custom methods that override base behavior
  - Thorough code review

**Risk: DI container issues with generics**
- **Scenario:** Type resolution fails with Generic[T]
- **Mitigation:**
  - Test DI registration explicitly
  - Use concrete type hints where needed
  - Fallback: Keep explicit registrations

**Risk: Performance regression**
- **Scenario:** Generic methods slower than specialized ones
- **Mitigation:**
  - Benchmark critical queries before/after
  - Unlikely for CRUD operations
  - Can optimize base methods if needed

---

## Rollout Considerations

**Deployment:**
- No special rollout needed
- Pure refactoring, no behavior changes
- Deploy with regular release

**Testing:**
- Run full test suite on staging
- Smoke test payment creation/retrieval
- No user-facing changes to verify

**Rollback:**
- Revert commit if issues found
- No data migration to rollback
- Low risk, easy rollback

---

## Acceptance Criteria
- [ ] PaymentRepository extends BaseRepository
- [ ] All duplicate CRUD methods removed
- [ ] Custom payment methods preserved
- [ ] All existing tests pass
- [ ] No breaking changes to public API
- [ ] Test coverage maintained at 100%
- [ ] DI container registration works
- [ ] Code review approved

When acceptance criteria are written as BDD scenarios, use the
project or ticket language for Gherkin keywords, scenario prose, and
actor names.
Reference Cucumber's official supported language list instead of
inventing translations:
https://cucumber.io/docs/gherkin/languages/
Include `# language: <code>` when writing feature-file-style blocks.

---

## Norms

[Project rules and conventions this change MUST follow. Populated
by the Norms / Safeguards autopopulator from `.claude/rules/INDEX.md`
at scope-render time. Do NOT hand-copy rules here — list manual
additions only.]

**Auto-populated rules** (filled by `Dev10x:ticket-scope` Phase 5):
- [Placeholder — renderer walks `.claude/rules/INDEX.md` and
  path-matches against affected files]

**Manual additions**:
- [e.g., "Generic type parameters must be `Protocol`s, not raw
  `TypeVar`s, to satisfy mypy strict mode in this codebase"]

---

## Safeguards

[Invariants and validation rules that must hold AFTER this change
ships. Distinct from `## Technical Risks` (rollout failures) —
Safeguards describe what must always be true **post-change**.]

**Invariants:**
- All `BaseRepository` subclasses preserve their pre-existing
  public method signatures
- DI container resolves `BaseRepository[T]` for every concrete
  subclass registered before the refactor

**Validation rules:**
- Generic type parameter `T` must be a `pydantic.dataclass` (not
  an arbitrary class) — enforced at registration time
- `BaseRepository.get(id)` raises `EntityNotFound` (typed
  exception) on miss, never returns `None`

**Authorization safeguards:**
- Refactor preserves existing repository-level permission checks
  (no method becomes implicitly more permissive)

---

## Out of Scope
- Refactoring other repositories (do in separate PRs)
- Adding new functionality to base class
- Performance optimizations (unless needed)
- Changing test patterns

---

## Story Points
**5 points** (1-2 days)

**Rationale:**
- Update BaseRepository (1 point)
- Refactor PaymentRepository (2 points)
- Test verification and fixes (1 point)
- Code review and adjustments (1 point)
