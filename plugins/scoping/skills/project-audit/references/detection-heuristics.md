# Detection Heuristics

Patterns and grep strategies for each audit phase.

## Tell Don't Ask Violations

Service code that reads model state then mutates externally:

```python
# VIOLATION: service checks model state, then sets it
if model.status == Status.PENDING:
    model.status = Status.APPROVED
    model.save()

# CORRECT: model owns its transitions
model.approve(approved_by=user_id)
```

**Grep patterns:**
- `\.status\s*==.*\n.*\.status\s*=` (read then write)
- `if.*\.is_.*:.*\n.*\.` (boolean check then external mutation)
- `getattr.*status.*setattr` (dynamic attribute access patterns)

**Heuristic:** For each model with a `status` field, check whether
status transitions happen inside model methods or in external
services/views.

## Anemic Domain Models

Models with state but no behavioral methods:

**Classification:**
- Count methods per model class excluding: `__str__`, `__repr__`,
  `Meta`, `save`, `delete`, `clean`, property getters
- 0 behavioral methods + has state fields = **ANEMIC**
- 0 behavioral methods + no state (only FKs) = DATA RECORD (ok)
- 1-2 behavioral methods + many state fields = **POTENTIALLY ANEMIC**

**Grep patterns:**
- `class\s+\w+Model.*:` followed by only field definitions
- Model files with no methods beyond boilerplate

**Framework-specific:**
- Django: check for models with only `CharField`, `IntegerField`,
  etc. and no custom methods
- SQLAlchemy: check for mapped classes with only Column definitions

## Module-Level Orchestration

External services orchestrating model behavior:

```python
# VIOLATION: service reaches into aggregate internals
def process_order(order):
    for item in order.items.all():
        item.status = "shipped"
        item.save()
    order.status = "fulfilled"
    order.save()

# CORRECT: aggregate owns orchestration
def process_order(order):
    order.fulfill()
```

**Grep patterns:**
- Service files with multiple `model.field = value` assignments
- Functions that iterate over related objects and mutate each one
- Transaction blocks that update multiple models independently

## Concurrency Gaps

Mutating operations missing protection:

**Required for each mutating operation:**
1. `@transaction.atomic` or `with transaction.atomic():`
2. `select_for_update()` on the queryset being modified
3. Unique constraints on business-critical fields
4. `IntegrityError` handling mapped to domain exceptions

**Grep patterns:**
- `.save()` or `.update()` without surrounding `transaction.atomic`
- `filter(...).update(...)` without `select_for_update()`
- `get_or_create` without unique constraint on lookup fields

**Framework-specific:**
- Django: check views/services with `Model.objects.filter().update()`
- SQLAlchemy: check for sessions without `with_for_update()`

## Value Object Candidates

Primitives with scattered validation:

**Indicators:**
- Same validation regex applied in multiple places
- `CharField` with `validators=[...]` that encodes business rules
- Helper functions like `normalize_phone()`, `validate_email()`
  called from multiple locations
- Constants like `MAX_LENGTH` defined per-field instead of
  centralized

**Grep patterns:**
- `validators=\[` on model fields (validation on storage, not domain)
- Repeated `re.match` or `re.compile` for the same pattern
- Functions named `validate_*`, `normalize_*`, `format_*` for
  domain concepts

## Cross-Context Query Use Case Candidates

Functions that resolve multiple DI protocols from different bounded
contexts to assemble a response — candidates for extraction into a
dedicated query use case class (per ADR-052 pattern).

**Detection rules — flag when ANY condition is met:**

1. **3+ protocol lookups** — same function body resolves 3+ published
   protocols from the DI container (`container[IXxxQuery]`,
   `container.get(IXxxRepository)`, or injected via constructor)
2. **20+ lines of data assembly** — function body spans 20+ lines
   assembling data from multiple bounded context protocols
3. **N+1 query patterns** — `get_by_id()` or `get_class()` called
   inside a loop where a batch variant exists (`get_by_ids()`,
   `get_classes()`)
4. **Domain→API type import** — a module outside `api/` imports from
   `api/types.py` (Strawberry types leaking into domain layer)

**Grep patterns:**
- `container\[I\w+Query\]` or `container\.get\(I\w+` (DI lookups)
- `for .* in .*:\n.*get_by_id\(` (N+1 in loop)
- `from.*api\.types import` in non-`api/` modules
- Functions with 3+ distinct `I\w+(Query|Repository)` type annotations

**Guidance when flagged:**
- Extract into a query use case class in `<bc>/queries.py`
- Return domain DTOs from `<bc>/dtos.py`, not Strawberry types
- Use batch protocol methods to eliminate N+1
- Reference ADR-052 for the full pattern

## Cross-Cutting Inconsistency

Same concept implemented differently across modules:

**Indicators:**
- Different error handling patterns (some raise, some return None)
- Mixed pagination approaches (cursor vs offset)
- Inconsistent naming (`get_by_id` vs `find_by_pk` vs `retrieve`)
- Some modules use DI, others instantiate directly

**Grep patterns:**
- `def get_by_` vs `def find_by_` vs `def retrieve_` across modules
- Mixed `raise` vs `return None` for not-found scenarios
- `import` patterns showing direct instantiation vs container usage
