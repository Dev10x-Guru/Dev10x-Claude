"""Tests for catalog_result.py: the result-dict shape every permission
catalog operation returns (GH-1432, GH-1449).

Previously untested directly — every `ensure_*`/`generalize`/`init`
caller exercised the shape incidentally through its own return value,
never pinning the shape itself."""

from dev10x.skills.permission.catalog_result import _result


class TestResult:
    def test_required_fields_only(self) -> None:
        result = _result(exit_code=0, messages=["ok"], errors=[])

        assert result == {
            "exit_code": 0,
            "messages": ["ok"],
            "errors": [],
            "total_added": 0,
            "files_changed": 0,
        }

    def test_all_fields_passed_through(self) -> None:
        result = _result(
            exit_code=1,
            messages=["m1"],
            errors=["e1"],
            total_added=3,
            files_changed=2,
        )

        assert result == {
            "exit_code": 1,
            "messages": ["m1"],
            "errors": ["e1"],
            "total_added": 3,
            "files_changed": 2,
        }

    def test_total_added_and_files_changed_default_to_zero(self) -> None:
        result = _result(exit_code=0, messages=[], errors=["e1"])

        assert result["total_added"] == 0
        assert result["files_changed"] == 0
