# E2E Coverage Map (worked example)

Maps source modules to feature files, tags, step definitions, and known
coverage gaps, so `Dev10x:qa-scope` Phase 3 can assess coverage without
searching the whole suite.

**This is one project's map, kept here as a shape to copy — not yours.**
The module paths, tags, and page objects below belong to a single
deployment. A project's own map belongs at tier 1 or 2 (see
`references/config-resolution.md`); Phase 3.1 skips the lookup entirely
when the project has no map, rather than matching against this one.

**Last updated:** 2026-02-09

## Module → E2E Mapping

### Payments & Square

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/payments/` | `crm/point_of_sale/square.feature` | `@dealer-crm-square` | `steps/crm.py` |
| `src/payments/` | `crm/point_of_sale/refunds.feature` | `@dealer-crm-refunds` | `steps/crm.py` |
| `src/square_oauth/` | `crm/point_of_sale/square.feature` | `@dealer-crm-square` | `steps/crm.py` |

**Covered scenarios:**
- Invoice generation (with/without customer email)
- Contactless payment link creation and sending
- Payment link viewing on Square side

**Known gaps:**
- Terminal device pairing/listing
- OAuth re-authorization after scope changes
- Payment refund edge cases
- Square webhook handling

### Quotes & Estimates

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/quotes/` | `crm/point_of_sale/estimates.feature` | `@dealer-crm-pos` | `steps/estimates.py` |

**Covered scenarios:**
- Work order creation
- Service line item management
- Estimate approval flow

**Known gaps:**
- Quote versioning
- Multi-service estimates
- Quote-to-invoice conversion edge cases

### Invoices

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/invoices/` | `crm/point_of_sale/invoices.feature` | `@dealer-crm-invoices` | `steps/invoices.py` |

**Covered scenarios:**
- Invoice creation and viewing
- Invoice line items

**Known gaps:**
- Invoice PDF generation
- Invoice email delivery
- Partial payment invoices

### Refunds

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/refunds/` | `crm/point_of_sale/refunds.feature` | `@dealer-crm-refunds` | `steps/crm.py` |

**Covered scenarios:**
- Basic refund flow

**Known gaps:**
- Partial refunds
- Refund with credit memo

### Returns

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/warehouse/` (returns) | `crm/point_of_sale/returns.feature` | `@dealer-crm-returns` | `steps/returns.py` |

**Note:** Currently tagged `@fixme` — tests may be broken.

**Known gaps:**
- Restock flow
- Vendor return flow
- Write-off flow

### Services

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/services/` | `crm/point_of_sale/estimates.feature` | `@dealer-crm-pos` | `steps/estimates.py` |

**Covered scenarios:**
- Service item management on work orders

### Customers

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/customers/` | `crm/point_of_sale/customer_required.feature` | `@dealer-crm-pos` | `steps/crm.py` |

**Covered scenarios:**
- Customer required before payment validation

**Known gaps:**
- Customer CRUD operations
- Customer search
- Customer merge

### Vehicles

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/vehicles/` | — | — | — |

**Known gaps:**
- No dedicated e2e coverage for vehicle management

### Tax

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/` (tax) | `crm/point_of_sale/tax.feature` | `@dealer-crm-tax` | `steps/crm.py` |

**Covered scenarios:**
- Tax group configuration
- State tire tax settings

### Shop Fees

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/` (shop fees) | `crm/point_of_sale/shop_fees.feature` | `@dealer-crm-shop-fees` | `steps/shop_fees.py` |

**Covered scenarios:**
- Shop fee configuration
- Fee type application to service groups

### Credit Memos

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/` (credit memos) | `crm/point_of_sale/credit_memos.feature` | `@dealer-crm-pos` | `steps/credit_memos.py` |

**Covered scenarios:**
- Credit memo issuance (admin/owner only)

### Scheduler / Booking

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/booking/` | `crm/point_of_sale/scheduler.feature` | `@dealer-crm-pos` | `steps/crm.py` |

### Purchase Orders

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/orders/` | `crm/purchase_order.feature` | `@crm-purchase-orders` | `steps/purchase_orders.py` |

### PartsTech Integration

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_pos/` (parts_tech) | `crm/point_of_sale/parts_tech.feature` | `@parts-tech` | `steps/crm.py` |

**Note:** Currently tagged `@fixme` — tests may be broken.

### Authentication

| app-pos Module | E2E Feature File | Tags | Step Definitions |
|---------------|-----------------|------|-----------------|
| `src/app_backend/` (auth) | `authentication.feature` | `@smoke-test`, `@dealer-crm` | `steps/authentication.py` |

### Modules Without E2E Coverage

| app-pos Module | Notes |
|---------------|-------|
| `src/app_pos/motor/` | Motor API integration — no e2e tests |
| `src/app_pos/vehicles/` | Vehicle management — no dedicated e2e |
| `src/app_pos/accounts/` | Account management — no e2e tests |
| `src/app_pos/auditor/` | Audit logging — no e2e tests |
| `src/emails/` | Email sending — no e2e tests |
| `src/tracking/` | Analytics tracking — no e2e tests |
| `src/reviews/` | Review management — no e2e tests |
| `src/public_access/` | Public-facing pages — no e2e tests |

## Page Objects

| Page Object | Location | Covers |
|-------------|----------|--------|
| CRM pages | `tests/pages/crm.py` | Work orders, estimates, invoices |
| ExampleCorp pages | `tests/pages/app.py` | General ExampleCorp UI |
| Base pages | `tests/pages/base.py` | Shared page utilities |

## Running E2E Tests by Tag

```bash
# Run specific feature area, from the resolved $E2E_ROOT
behave --tags=@dealer-crm-square
behave --tags=@dealer-crm-pos
behave --tags=@dealer-crm-invoices
```

## Maintenance

Update this file when:
- New e2e feature files are added to app-e2e
- New app-pos modules are created
- Coverage gaps are filled
- Feature files are tagged `@fixme` or un-fixed
