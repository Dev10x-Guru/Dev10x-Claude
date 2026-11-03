# Advanced Patterns

Reference for `dev10x:py-mockito`: stubbing shapes beyond a plain
method on a collaborator class.

## Stubbing Callable Classes (`__call__`)

Classes used as callables (command pattern, handlers) are stubbed
via `__call__`:

```python
when(PaymentGateway).__call__(...).thenReturn(None)
when(OrderMapper).__call__(...).thenReturn(mapped_order)
when(EventPublisher).__call__(...).thenRaise(ConnectionError)

verify(PaymentGateway).__call__(data=payload)
verify(EventPublisher, times=0).__call__(...)
```

## Chaining Stubs for Fluent APIs

Stub method chains (e.g., Django QuerySet):

```python
@pytest.fixture(autouse=True)
def stub_warehouse_lookup(self, when, warehouse):
    manager = Warehouse.objects
    when(manager).using("replica").thenReturn(Warehouse.objects)
    when(manager).get(id=warehouse.id).thenReturn(warehouse)

@pytest.fixture(autouse=True)
def stub_supplier_query(self, when, manager, suppliers):
    qs = mock()
    when(Supplier.objects).using("replica").thenReturn(manager)
    when(manager).filter(created_at__gte=ANY).thenReturn(qs)
    when(qs).iterator().thenReturn(suppliers)
```

## Stubbing Modules and Functions

Stub module-level functions or third-party library calls:

```python
# Stub a validation function on a module
when(webhook_module).is_valid_signature(
    request_body=payload,
    signature_header=signature,
    signature_key=key,
    notification_url=url,
)

# Stub requests.post
when(requests).post(...).thenReturn(
    MagicMock(status_code=200)
)
```

## Stubbing Private Methods

Stub internal methods to isolate the unit under test:

```python
when(CheckoutCreator)._validate_totals(...).thenReturn()
when(PaymentHandler)._query_reference(...).thenReturn(None)
when(CatalogProvider)._list_items(...).thenReturn(items)
```

## Stubbing with a DI Container

When the SUT is resolved from a DI container, stub its dependencies
at the class level — the container injects real instances, but their
methods are stubbed:

```python
class TestQuoteService:
    @pytest.fixture(autouse=True)
    def setup(self, container):
        self.service = container.get(QuoteService)

    @pytest.fixture(autouse=True)
    def stub_provider(self, when, cart):
        when(CartProvider).get_cart(...).thenReturn(cart)

    @pytest.fixture(autouse=True)
    def stub_builder(self, when, quote):
        when(QuoteBuilder).__call__(...).thenReturn(quote)

    @pytest.fixture
    def result(self, cart_id, user_id):
        return self.service.create_quote(
            cart_id=cart_id,
            user_id=user_id,
        )

    def test_returns_quote(self, result, quote):
        assert result == quote

    @pytest.mark.usefixtures("result")
    def test_calls_provider(self, cart_id):
        verify(CartProvider).get_cart(cart_id=cart_id)
```

## Stubbing Logger Calls

Verify structured logging without capturing output:

```python
when(log).info("Webhook received", payload=payload)

# Later: verify the log call happened
verify(log).error(
    "Event publishing failed",
    error=ANY,
    channel=channel_name,
)
```
