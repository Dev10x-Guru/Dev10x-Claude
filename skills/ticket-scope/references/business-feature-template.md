# Business Feature Scoping Template

Use this template for features that provide direct business value and will be announced to users.

---

# [Feature Title]

## Summary for Business
[1-2 paragraph overview in business-friendly language]

## Business Value
- **Who benefits:** [users/teams/departments]
- **Impact:** [describe the benefit or problem solved]
- **Priority:** [why this work is important now]

## Release Notes Draft
**New Feature: [User-Facing Title]**

[User-friendly description of what's new. Focus on benefits and how to use it. Avoid technical jargon.]

Example:
"We've added the ability to apply discount codes during checkout. Store managers can now create promotional codes with expiration dates through the admin panel. Customers will see the discount applied automatically when they enter a valid code."

---

## Technical Implementation Plan

### Problem Statement
[Technical description of what we're building and why]

### Architecture
**Components Affected:**
- **Repositories:**
  - New: `DiscountRepository` (CRUD for discount codes)
  - Existing: `PaymentRepository` (apply discounts)

- **Services:**
  - New: `DiscountService` (business logic for code validation)
  - Existing: `PaymentCalculator` (integrate discount)

- **Models:**
  - New: `DiscountCode` (id, code, amount, expiry, usage_limit)

- **DTOs:**
  - New: `DiscountDto`, `ApplyDiscountDto`

- **GraphQL:**
  - New mutations: `createDiscountCode`, `applyDiscountCode`
  - New queries: `listDiscountCodes`, `validateDiscountCode`

**Database Changes:**
- New table: `quotes_discountcode`
- New column: `quotes_workorder.discount_code_id` (FK)
- Migration: Auto-generated + custom for indexes

### Entities

[Data shapes introduced or modified by this change. Use this section to
make property schemas and relationships explicit — the Architecture
section names *which* components are affected; Entities names *what*
data they carry.]

**New entities:**

| Entity | Properties | Relationships |
|--------|-----------|---------------|
| `DiscountCode` | `id`, `code` (unique), `amount`, `expiry`, `usage_limit`, `created_at` | M:N with `Quote` via `quotes_discountcode_usages` |

**Modified entities:**

| Entity | Changes |
|--------|---------|
| `WorkOrder` | Adds nullable `discount_code_id` FK to `DiscountCode` |

Note any uniqueness constraints, indexes, ordering, or cardinality
requirements that downstream code must preserve.

### Implementation Steps

1. **Create DiscountCode Model**
   - File: `src/app_pos/quotes/discounts/models.py`
   - Pattern: Django model with proper indexes
   - Reference: `src/app_pos/quotes/models.py:WorkOrder` for FK patterns

2. **Create Discount DTOs**
   - File: `src/app_pos/quotes/discounts/dto.py`
   - Pattern: `pydantic.dataclasses` frozen=True
   - Reference: `src/app_pos/quotes/dto.py:QuoteDto`

3. **Create DiscountRepository**
   - File: `src/app_pos/quotes/discounts/repository.py`
   - Pattern: `@injectable_dataclass` with Permissions
   - Methods: `create()`, `get_by_code()`, `validate()`, `increment_usage()`
   - Reference: `src/app_pos/quotes/repository.py:WorkOrderRepository`

4. **Create DiscountService**
   - File: `src/app_pos/quotes/discounts/service.py`
   - Pattern: `@injectable_dataclass`
   - Logic: Code validation, expiry check, usage limit check
   - Reference: `src/app_pos/quotes/services/service.py:ServiceEstimateService`

5. **Update PaymentCalculator**
   - File: `src/app_pos/quotes/pricing/calculator.py`
   - Add: Discount application logic
   - Reference: Existing discount handling (if any)

6. **Register in DI Container**
   - File: `src/app/container/__init__.py`
   - Register: `DiscountRepository`, `DiscountService`
   - Pattern: Follow existing registration patterns

7. **Create GraphQL Schema**
   - File: `src/app_pos/quotes/discounts/api/schema.py`
   - Types: `DiscountCodeNode`, `ApplyDiscountInput`
   - Reference: `src/app_pos/quotes/api/schema.py`

8. **Create GraphQL Mutations**
   - File: `src/app_pos/quotes/discounts/api/mutations.py`
   - Mutations: `createDiscountCode`, `applyDiscountCode`
   - Reference: `src/app_pos/quotes/api/mutations.py:WorkOrderCheckout`

9. **Create GraphQL Queries**
   - File: `src/app_pos/quotes/discounts/api/queries.py`
   - Queries: `listDiscountCodes`, `validateDiscountCode`
   - Reference: `src/app_pos/quotes/api/queries.py`

10. **Create Database Migration**
    - Command: `python manage.py makemigrations`
    - Review: Check indexes on `code` (unique), `expiry` fields
    - Apply: `python manage.py migrate`

11. **Write Tests** (Follow CLAUDE.md patterns)
    - Unit: `src/app_pos/quotes/discounts/tests/test_service.py`
    - Integration: `src/app_pos/quotes/discounts/api/tests/test_mutations.py`
    - Fakers: Create `DiscountCodeFaker` in `tests/fakers.py`
    - Pattern: Result fixtures, parametrization, 100% coverage

### Code References
- `src/app_pos/quotes/models.py:WorkOrder` - Model patterns
- `src/app_pos/quotes/repository.py:WorkOrderRepository` - Repository patterns
- `src/app_pos/quotes/pricing/calculator.py` - Price calculation logic
- `src/app_pos/quotes/api/mutations.py` - GraphQL mutation patterns
- `src/app_pos/quotes/tests/fakers.py` - Faker patterns

### Acceptance Criteria
- [ ] Store admin can create discount codes with expiry dates
- [ ] Codes can have usage limits (single use or multi-use)
- [ ] Customers can apply valid codes during checkout
- [ ] Invalid/expired codes show clear error messages
- [ ] Discount appears in payment summary before final charge
- [ ] Used codes are tracked (can't reuse single-use codes)
- [ ] Admin can list and view active discount codes
- [ ] Tests cover all edge cases (expired, invalid, usage limit)

### Norms

[Project rules and conventions this change MUST follow. The Norms /
Safeguards autopopulator (`Dev10x:ticket-scope` Phase 5) renders the
matched rules from `.claude/rules/INDEX.md` inline at scope-render
time. Do NOT hand-copy rules here — list manual additions only.]

**Auto-populated rules** (rendered at scope-generation time):
- [Placeholder — `Dev10x:ticket-scope` Phase 5 renderer fills this
  by walking `.claude/rules/INDEX.md` and path-matching against the
  files in Architecture / Implementation Steps.]

**Manual additions** (project conventions discovered during scoping
that aren't in INDEX.md yet):
- [e.g., "Discount-code copy must round-trip through i18n catalogue —
  no hard-coded English strings"]

Norms answer: *what must this code do to fit existing patterns?*

### Safeguards

[Invariants and validation rules that must hold AFTER this change
ships. Distinct from `### Risks & Mitigation` below, which lists
what could go wrong **during rollout**. Safeguards describe what
must always be true **post-change**.]

**Invariants:**
- A `WorkOrder` can have at most one active `DiscountCode` applied
- `DiscountCode.usage_count` must never exceed `usage_limit`
- A discount cannot reduce the `WorkOrder` total below zero

**Validation rules:**
- `DiscountCode.code` matches `^[A-Z0-9-]{4,32}$`
- `expiry` must be in the future when the code is created
- `amount` must be positive

**Authorization safeguards:**
- Only `store_admin` role can create or deactivate discount codes
- Customers cannot view raw `usage_count` of any code

Safeguards answer: *what must always be true after this change?*

### Risks & Mitigation

**Risk: Race condition on usage limit**
- **Scenario:** Two customers apply same code simultaneously
- **Mitigation:** Use database transaction with SELECT FOR UPDATE on usage increment

**Risk: Discount abuse (code sharing)**
- **Scenario:** Codes shared publicly beyond intended audience
- **Mitigation:** Add rate limiting, per-customer usage tracking in Phase 2

**Risk: Breaking change to payment flow**
- **Scenario:** Existing payment calculations affected
- **Mitigation:** Thorough testing of existing flows, feature flag for rollout

### Rollout Strategy

**Phase 1: Internal Testing**
1. Deploy behind feature flag `enable_discount_codes`
2. Test with internal accounts only
3. Verify no impact on existing payment flows

**Phase 2: Limited Rollout**
1. Enable for 10% of stores
2. Monitor error rates, payment success rates
3. Collect feedback from pilot users

**Phase 3: Full Rollout**
1. Enable for all stores
2. Announce via release notes
3. Monitor adoption metrics

**Rollback Plan:**
- Disable feature flag if issues found
- No data rollback needed (codes are additive)
- Existing orders without codes unaffected

### Monitoring

**Metrics to track:**
- `discount_code_validations_total` (counter)
- `discount_code_validation_errors_total` (counter by error type)
- `discount_codes_applied_total` (counter)
- `discount_amount_total` (gauge - total discounts applied)

**Alerts:**
- Alert if validation error rate > 20%
- Alert if applied discounts exceed expected threshold

**Logs:**
- Log discount code validation results (code, valid/invalid reason)
- Log discount applications (code, order, amount)

### Story Points
**8 points** (3-5 days)

**Rationale:**
- New models, repositories, services (3 points)
- GraphQL schema + mutations (2 points)
- Migration + validation logic (2 points)
- Testing + feature flag rollout (1 point)
