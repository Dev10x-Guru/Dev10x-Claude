import pytest

from dev10x.domain.common.result import (
    ErrorResult,
    ResultProtocol,
    SuccessResult,
    err,
    ok,
    to_wire,
)


class TestOk:
    @pytest.fixture()
    def result(self) -> SuccessResult[dict]:
        return ok({"key": "value"})

    def test_value(self, result: SuccessResult[dict]) -> None:
        assert result.value == {"key": "value"}

    def test_to_dict_with_dict_value(self, result: SuccessResult[dict]) -> None:
        assert result.to_dict() == {"key": "value"}

    def test_to_dict_returns_copy(self, result: SuccessResult[dict]) -> None:
        # ADR-0009: to_dict returns a fresh dict, not the wrapped object.
        assert result.to_dict() == {"key": "value"}
        assert result.to_dict() is not result.value

    def test_to_dict_rejects_non_mapping(self) -> None:
        # ADR-0009: a SuccessResult reaching the MCP boundary must wrap a
        # Mapping; a non-Mapping value now fails loud rather than silently
        # producing {"value": ...} via a runtime isinstance branch.
        with pytest.raises((TypeError, ValueError)):
            ok("simple").to_dict()

    def test_is_success_result(self, result: SuccessResult[dict]) -> None:
        assert isinstance(result, SuccessResult)
        assert not isinstance(result, ErrorResult)


class TestErr:
    @pytest.fixture()
    def result(self) -> ErrorResult:
        return err("something failed")

    def test_error(self, result: ErrorResult) -> None:
        assert result.error == "something failed"

    def test_to_dict(self, result: ErrorResult) -> None:
        assert result.to_dict() == {"error": "something failed"}

    def test_to_dict_with_details(self) -> None:
        result = err("conflict", blocked=True, output="details")
        assert result.to_dict() == {
            "error": "conflict",
            "blocked": True,
            "output": "details",
        }

    def test_is_error_result(self, result: ErrorResult) -> None:
        assert isinstance(result, ErrorResult)
        assert not isinstance(result, SuccessResult)


class TestFrozen:
    def test_success_immutable(self) -> None:
        result = ok({"a": 1})
        with pytest.raises(AttributeError):
            result.value = {"b": 2}  # type: ignore[misc]

    def test_error_immutable(self) -> None:
        result = err("fail")
        with pytest.raises(AttributeError):
            result.error = "other"  # type: ignore[misc]


class TestResultProtocol:
    """ADR-0009: the MCP boundary can assert against ResultProtocol."""

    def test_success_satisfies_protocol(self) -> None:
        assert isinstance(ok({"a": 1}), ResultProtocol)

    def test_error_satisfies_protocol(self) -> None:
        assert isinstance(err("x"), ResultProtocol)

    def test_object_without_to_dict_does_not_satisfy(self) -> None:
        assert not isinstance(object(), ResultProtocol)


class TestToWire:
    """ADR-0009: the @server.tool() boundary routes its Result through to_wire."""

    def test_success_encodes_to_dict(self) -> None:
        assert to_wire(ok({"a": 1})) == {"a": 1}

    def test_error_encodes_to_dict(self) -> None:
        assert to_wire(err("boom", code=2)) == {"error": "boom", "code": 2}

    def test_raises_on_raw_dict(self) -> None:
        # A handler that forgot to return ok()/err() yields a bare dict,
        # which lacks to_dict() and must fail loud at the boundary rather
        # than at JSON-encode time.
        with pytest.raises(TypeError):
            to_wire({"already": "encoded"})  # type: ignore[arg-type]

    def test_raises_on_object_without_to_dict(self) -> None:
        with pytest.raises(TypeError):
            to_wire(object())  # type: ignore[arg-type]
