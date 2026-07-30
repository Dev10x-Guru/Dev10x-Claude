# Bug Fix Scoping Template

Use this template for fixing reported bugs from customers, support, or production monitoring.

---

# [Bug Fix Title]

## Bug Description

**Reported by:** [Customer Support / Sentry / Internal QA / Production User]
**Frequency:** [How often - "Intermittent" / "Always" / "Under X conditions"]
**Impact:** [User impact - "Checkout fails" / "Data incorrect" / "UI broken"]
**Severity:** [High / Medium / Low]

[Detailed description of the incorrect behavior]

Example:
"When a customer applies a tax-exempt purchase to a work order, the Square payment amount includes sales tax incorrectly. This causes the customer to be overcharged, and the work order total doesn't match the payment amount."

**How to reproduce:**
1. Create work order for tax-exempt customer
2. Add taxable items (tires)
3. Process Square terminal checkout
4. Observe: Square amount includes tax, work order doesn't

**Expected behavior:**
Square payment amount should exclude sales tax for tax-exempt customers, matching the work order total.

**Actual behavior:**
Square payment includes sales tax even for tax-exempt customers.

---

## Root Cause Analysis

**Why this happens:**

[Technical explanation of the bug's cause]

Example:
1. Work order correctly applies tax exemption during quote calculation
2. Tax exemption is stored in `Customer.tax_exemption` field
3. `OrderConverter.__call__()` generates Square order dynamically
4. Bug: `OrderConverter` reads tax settings via `TaxSettingsRepository.get_by_store_id()` but doesn't read customer tax exemption
5. Result: Square order always includes taxes, ignoring customer-level exemption

**Code location:**
- `src/payments/square/orders.py:OrderConverter.__call__()` (line 45-70)
  - Missing: Customer tax exemption lookup
  - Uses: `TaxSettingsRepository.get_by_store_id()` only

- `src/app_pos/quotes/repository.py:WorkOrderRepository.tax_exemption()` (line 156)
  - Correct: Reads customer exemption properly
  - Not used: By OrderConverter

**When bug was introduced:**
- Likely present since tax exemption feature added
- Not caught because tax-exempt customer tests missing in Square integration tests

---

## Solution

**Fix approach:**

[Technical solution description]

Example:
1. Update `OrderConverter.__call__()` to accept `tax_exemption: TaxExemption` parameter
2. Update `WorkOrderCheckoutCreator.create_checkout()` to pass tax exemption:
   - Read from `WorkOrderRepository.tax_exemption(work_order_id)`
   - Pass to `OrderConverter`
3. Update `OrderConverter._get_taxes()` to respect tax exemption:
   - If `TaxExemption.APPLY_NO_TAXES`, return empty taxes
   - If `TaxExemption.APPLY_NO_SALES_TAX`, exclude sales tax
   - If `TaxExemption.APPLY_ALL_TAXES`, use current behavior

**Why this fixes it:**

[Explanation of why solution works]

Example:
- OrderConverter will now receive customer tax exemption status
- Square order will be generated with correct tax amounts
- Matches work order tax calculation logic
- No breaking changes to other payment flows

---

## Implementation Steps

1. **Update OrderConverter to Accept Tax Exemption**
   - File: `src/payments/square/orders.py`
   - Method: `OrderConverter.__call__(work_order, tax_exemption: TaxExemption)`
   - Add parameter with default `TaxExemption.APPLY_ALL_TAXES` (backwards compatible)
   - Reference: `src/app_pos/quotes/pricing/taxes/dto.py:TaxExemption`

2. **Update OrderConverter._get_taxes() to Respect Exemption**
   - File: `src/payments/square/orders.py`
   - Method: `OrderConverter._get_taxes()`
   - Logic:
     ```python
     if self.tax_exemption == TaxExemption.APPLY_NO_TAXES:
         return {}
     if self.tax_exemption == TaxExemption.APPLY_NO_SALES_TAX:
         return {k: v for k, v in taxes.items() if k != 'SALES'}
     return taxes
     ```
   - Reference: `src/app_pos/quotes/pricing/calculator.py` for exemption logic

3. **Update WorkOrderCheckoutCreator to Pass Tax Exemption**
   - File: `src/payments/square/terminal.py`
   - Method: `WorkOrderCheckoutCreator.create_checkout()`
   - Add:
     ```python
     tax_exemption = self.work_order_repo.tax_exemption(work_order_id)
     order = self.order_converter(work_order, tax_exemption)
     ```
   - Reference: Existing `work_order_repo` usage

4. **Write Test for Bug Scenario**
   - File: `src/payments/square/tests/test_orders.py`
   - Test class: `TestOrderConverterWithTaxExemption`
   - Tests:
     - `test_no_taxes_for_fully_exempt_customer()`
     - `test_no_sales_tax_for_sales_exempt_customer()`
     - `test_all_taxes_for_non_exempt_customer()`
   - Pattern: Parametrize with different `TaxExemption` values
   - Faker: `WorkOrderFaker.create(customer__tax_exemption=TaxExemption.APPLY_NO_SALES_TAX)`
   - Reference: `src/app_pos/quotes/tests/test_pricing.py` for tax exemption tests

5. **Write Integration Test**
   - File: `src/payments/square/terminal/tests/test_terminal.py`
   - Test: `test_checkout_respects_customer_tax_exemption()`
   - Verify: Square order amount excludes tax for exempt customer
   - Reference: Existing terminal checkout tests

6. **Run Tests**
   - Command: `Skill(Dev10x:py-test src/payments/square/tests/ src/payments/square/terminal/tests/)`
   - Verify: All tests pass, new bug scenario covered

---

## Code References
- `src/payments/square/orders.py:OrderConverter` (line 45-70) - Bug location
- `src/payments/square/terminal.py:WorkOrderCheckoutCreator` (line 89) - Needs update
- `src/app_pos/quotes/repository.py:WorkOrderRepository.tax_exemption` (line 156) - Correct logic
- `src/app_pos/quotes/pricing/calculator.py` - Tax exemption patterns
- `src/payments/square/tests/test_orders.py` - Existing tests to extend

---

## Acceptance Criteria
- [ ] Tax-exempt customers are NOT charged sales tax in Square orders
- [ ] Partially exempt customers only charged applicable taxes
- [ ] Non-exempt customers still charged all taxes (no regression)
- [ ] Square order amount matches work order total
- [ ] Existing payment flows unaffected
- [ ] Tests added for all exemption scenarios
- [ ] Bug no longer reproducible in staging
- [ ] Test coverage maintained at 100%

When acceptance criteria are written as BDD scenarios, use the
project or ticket language for Gherkin keywords, scenario prose, and
actor names.
Reference Cucumber's official supported language list instead of
inventing translations:
https://cucumber.io/docs/gherkin/languages/
Include `# language: <code>` when writing feature-file-style blocks.

---

## Entities

[Data shapes touched by this fix. For bug fixes, the entities are
usually the existing types whose contracts were silently violated.
Listing them helps `Dev10x:spec-sync` detect future drift.]

**Affected entities:**

| Entity | Property used | Bug touched |
|--------|---------------|-------------|
| `Customer` | `tax_exemption: TaxExemption` | Read path missing |
| `WorkOrder` | tax calc honors `tax_exemption` | Correct already |
| `SquareOrder` | tax lines | Was ignoring exemption |

Bug fixes rarely introduce new entities. When they do (e.g., a
new typed exception), list them here so the spec covers the new
surface.

---

## Rollout

**Testing:**
1. Deploy to staging
2. Test with tax-exempt customer accounts:
   - Fully exempt (no taxes)
   - Sales exempt (labor tax only)
   - Non-exempt (all taxes)
3. Verify Square order amounts match work order totals

**Deployment:**
- Deploy in regular release cycle
- No migration needed
- Monitor Sentry for related errors

**Monitoring:**
- Watch for `SquareOrderAmountMismatchError` (if exists)
- Monitor customer support tickets about overcharges
- Check Square payment success rates

**Rollback:**
- Simple code revert if issues
- No data to rollback
- Low risk change

---

## Norms

[Project rules and conventions this fix MUST follow. Populated by
the Norms / Safeguards autopopulator (`Dev10x:ticket-scope`
Phase 5).]

**Auto-populated rules**:
- [Placeholder — renderer walks `.claude/rules/INDEX.md` matching
  affected files (e.g., `src/payments/square/**`)]

**Manual additions**:
- [e.g., "Square integration tests must use the recorded-cassette
  fixture, not live API calls"]

---

## Safeguards

[Invariants that must hold AFTER this fix ships. Distinct from the
`## Rollout` section, which describes monitoring during deploy.
Safeguards describe the **post-fix invariant** that the regression
test pins down.]

**Invariants:**
- `SquareOrder.tax_total == WorkOrder.tax_total` for every order,
  regardless of customer tax-exemption status
- `OrderConverter._get_taxes()` reads `tax_exemption` from its
  caller, never from a stale cache or globals

**Validation rules:**
- `TaxExemption` enum is exhaustive — `_get_taxes()` raises on
  unknown variants instead of silently returning all taxes
- Tax-exempt customer paths are covered by parametrized tests over
  all three `TaxExemption` values

**Authorization safeguards:**
- Only the `WorkOrderRepository.tax_exemption()` path may set the
  exemption on a Square order — no callers may pass it directly

---

## Resolution for Release Notes

**Fixed: Tax-exempt customers charged incorrect amounts**

We've fixed a bug where tax-exempt customers were incorrectly charged sales tax when paying through Square terminal checkout. The payment amount now correctly reflects the customer's tax exemption status, matching the work order total.

**Impact:** Tax-exempt customers will no longer be overcharged during checkout.

---

## Story Points
**3 points** (~1 day)

**Rationale:**
- Small code change (1 point)
- Tests for bug scenario (1 point)
- Testing and verification (1 point)
- Well-understood fix, low complexity
