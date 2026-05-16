import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok


class TestOk:
    @pytest.fixture()
    def result(self) -> SuccessResult[dict]:
        return ok({"key": "value"})

    def test_value(self, result: SuccessResult[dict]) -> None:
        assert result.value == {"key": "value"}

    def test_to_dict_with_dict_value(self, result: SuccessResult[dict]) -> None:
        assert result.to_dict() == {"key": "value"}

    def test_to_dict_with_non_dict_value(self) -> None:
        result = ok("simple")
        assert result.to_dict() == {"value": "simple"}

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
