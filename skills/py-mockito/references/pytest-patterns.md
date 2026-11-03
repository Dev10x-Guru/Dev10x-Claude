# Pytest Integration Patterns

Reference for `dev10x:py-mockito`: cleanup and fixture patterns that
keep mockito stubs scoped to the tests that declare them.

## Cleanup with `unstub()`

### Why Cleanup Matters

python-mockito patches its targets globally, so a stub that outlives
its test leaks into the next one. The pytest-mockito `when` fixture
unstubs at the end of every test, so function-scoped stubs taken
through it need no cleanup. Clean up yourself only when a stub
escapes that teardown: `mockito.when` imported at module level, or a
fixture scoped wider than the test.

### Yield + Unstub Pattern (wider-scoped fixtures)

```python
from mockito import unstub, when


@pytest.fixture(scope="class")
def stub_token_repository(token):
    when(TokenRepository).get_access_token(...).thenReturn(token)
    yield
    unstub(TokenRepository)
```

### Targeted vs Global Unstub

```python
unstub(TokenRepository)  # remove stubs on one class
unstub()                  # remove ALL stubs everywhere
```

### Autouse Fixture — No Cleanup Needed

A function-scoped fixture that takes the `when` fixture is unstubbed
at test teardown, so it needs no `yield` or `unstub`:

```python
@pytest.fixture(autouse=True)
def stub_auth(self, when, session_user):
    when(AuthService).get_user(...).thenReturn(session_user)
```

## The `when` Fixture (pytest-mockito)

`pytest-mockito` provides `when` as a built-in fixture. Use it as a
parameter — no import needed in the test:

```python
def test_returns_order(self, when, order):
    when(OrderRepository).find_by_id(...).thenReturn(order)
    result = self.service.get_order(order_id=order.id)
    assert result == order
```

## Autouse Stub Fixtures

Stub collaborators that every test in the class needs:

```python
@pytest.mark.django_db
class TestOrderService:
    @pytest.fixture(autouse=True)
    def setup(self, container):
        self.service = container.get(OrderService)

    @pytest.fixture(autouse=True)
    def stub_pricing_repository(self, when, price_list):
        when(PricingRepository).get_for_region(...).thenReturn(price_list)

    @pytest.fixture(autouse=True)
    def stub_shipping_rates(self, when, shipping_rates):
        when(ShippingRateRepository).get_for_region(...).thenReturn(shipping_rates)
```

## Conditional Stubs with Markers

Suppress a signal handler by default, but let specific tests opt in:

```python
# conftest.py
@pytest.fixture(autouse=True)
def suppress_order_placed(request, when):
    if "enable_order_placed" in request.keywords:
        return
    when(OrderPlacedHandler).__call__(...)
```

```python
# test_integration.py
@pytest.mark.enable_order_placed
def test_sends_confirmation_email(self, order):
    ...  # signal handler runs for this test only
```

Register the marker (`markers = ["enable_order_placed: ..."]` under
`[tool.pytest.ini_options]`) or `--strict-markers` rejects it.

## Result Fixture + Verification

Run the SUT once in a fixture, verify calls and inspect results
across multiple test methods:

```python
class TestCheckoutCreator:
    @pytest.fixture(autouse=True)
    def setup(self, container):
        self.creator = container.get(CheckoutCreator)

    @pytest.fixture(autouse=True)
    def stub_order_mapper(self, when, mapped_order):
        when(OrderMapper).__call__(...).thenReturn(mapped_order)

    @pytest.fixture
    def result(self, order, payment_method):
        return self.creator.create(
            order=order,
            payment_method=payment_method,
        )

    def test_returns_checkout_reference(self, result):
        assert result.reference_id is not None

    @pytest.mark.usefixtures("result")
    def test_calls_order_mapper(self, order):
        verify(OrderMapper).__call__(order=order)

    @pytest.mark.usefixtures("result")
    def test_does_not_duplicate_invoice(self):
        verify(InvoiceCreator, times=0).create(...)
```
