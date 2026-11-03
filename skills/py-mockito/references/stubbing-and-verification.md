# Stubbing and Verification

Reference for `dev10x:py-mockito`: how to declare stubs, assert
interactions, capture arguments, and build standalone mocks.

## Stubbing with `when()`

### Ellipsis — Match Any Arguments

Use `...` (Ellipsis) when the test doesn't care about specific arguments.
Focus stays on the return value or side effect:

```python
# Stub a repository — any arguments accepted
when(ProductRepository).find_by_id(...).thenReturn(product)

# Stub a callable class (classes with __call__)
when(PaymentGateway).__call__(...).thenReturn(None)

# Stub a signal handler to suppress side effects
when(AuditLogHandler).__call__(...)
```

### Named Arguments — Precise Matching

Use named parameters when the test must verify specific input routing:

```python
when(OrderRepository).get_by_customer(
    customer_id=customer_id,
).thenReturn(order)

when(TokenRepository).get_access_token(
    account_id=account_id,
).thenReturn(token)
```

### Matchers — Flexible Matching

Use `ANY` for positional args or `any_(type)` for typed matching:

```python
from mockito import ANY, any_

# ANY matches any single value
when(QuerySet).filter(created_at__gte=ANY).thenReturn(qs)

# any_(type) matches any value of that type
when(batch_processor).__call__(Model, any_(list))
```

### Behaviors — thenReturn and thenRaise

```python
# Return a value
when(SettingsRepository).get(...).thenReturn(settings)

# Return None (void stub)
when(EventPublisher).__call__(...).thenReturn(None)

# Suppress without return (implicit None)
when(SignalHandler).__call__(...)

# Raise an exception
when(TokenRepository).get_access_token(...).thenRaise(
    Token.DoesNotExist("No token found")
)

when(ExternalApi).__call__(...).thenRaise(
    TimeoutError("Service unavailable")
)
```

## Verification with `verify()`

### Basic Verification — Called Once

```python
verify(PaymentGateway).__call__(data=webhook_payload)

verify(OrderRepository).save(
    order_id=order_id,
    status=OrderStatus.COMPLETED,
)
```

### Times — Control Call Count

```python
# Never called (negative assertion)
verify(PaymentGateway, times=0).__call__(...)
verify(RefundHandler, times=0).process(...)

# Called exactly N times
verify(BatchProcessor, times=2).__call__(...)

# Combine with Ellipsis for "never called with any args"
verify(InvoiceCreator, times=0).create(...)
# Or with specific args for "called once with these args"
verify(InvoiceCreator, times=1).create(order_id=order_id)
```

### verifyZeroInteractions — Never Touched

Assert that a collaborator was never called at all. Useful for
testing early-exit/guard-clause paths:

```python
def test_skips_when_not_configured(self, when):
    when(requests)  # register for tracking, no stub behavior
    EventPublisher()(channel="test", event={"key": "val"})
    verifyZeroInteractions(requests)
```

## Argument Capture with `captor()`

### Basic Capture — Single Value

Capture an argument passed to a stubbed method for detailed inspection:

```python
@pytest.fixture
def captured_payment(self, when, webhook_payload):
    payment = captor()
    when(TransactionRepository).save(payment=payment)
    self.handler(data=webhook_payload)
    return payment.value  # the actual Payment object passed

def test_payment_amount(self, captured_payment, expected_amount):
    assert captured_payment.amount == expected_amount

def test_payment_currency(self, captured_payment):
    assert captured_payment.currency == Currency.USD
```

### Capture with Verify

Capture and assert in the same test body:

```python
def test_saves_calculated_totals(self, order_id, result):
    totals_captor = captor()
    verify(TotalsRepository).save(
        totals=totals_captor,
        order_id=order_id,
    )
    assert totals_captor.value.grand_total == result.grand_total
```

### Typed Capture — any_() with captor

Combine captor with a type matcher for multiple captures:

```python
def test_processes_in_batches(self, items, batch_processor):
    migration(apps=apps, schema_editor=editor)
    batches = captor(any_(list))
    verify(batch_processor, times=2).__call__(Model, batches)
    assert {len(b) for b in batches.all_values} == {10, 5}
    assert set(chain(*batches.all_values)) == set(items)
```

### Multiple Captures — `.all_values`

When a method is called multiple times, `.all_values` returns all
captured arguments as a list:

```python
verify(processor, times=3).__call__(item_captor)
all_items = item_captor.all_values  # [item1, item2, item3]
assert set(all_items) == set(expected_items)
```

## Mock Objects with `mock()`

### Standalone Mocks

Create a mock when you need an object that doesn't correspond to a
real class (e.g., a schema editor in migrations):

```python
@pytest.fixture
def schema_editor(self):
    return mock()
```

### Callable Mocks

Create a mock with a specific callable behavior:

```python
@pytest.fixture
def item_transformer(self):
    return mock({"__call__": lambda item: item})
```
