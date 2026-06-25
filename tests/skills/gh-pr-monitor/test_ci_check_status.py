"""Tests for ci-check-status.py verdict logic."""

import importlib.util
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "ci_check_status",
    _repo_root / "skills" / "gh-pr-monitor" / "scripts" / "ci-check-status.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

compute_verdict = _mod.compute_verdict
# The shim re-exports via `import *`; the functions live in the real
# module, so cross-function calls (get_annotated_checks → get_checks)
# resolve names there. Patch the real module, not the shim.
_impl = sys.modules[compute_verdict.__module__]


class TestComputeVerdict:
    def test_empty_checks_returns_empty(self):
        result = compute_verdict(checks=[])
        assert result["verdict"] == "empty"
        assert result["total"] == 0

    def test_all_passing_returns_green(self):
        checks = [
            {"name": "build", "bucket": "pass"},
            {"name": "test", "bucket": "pass"},
            {"name": "lint", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks, mergeable="MERGEABLE")
        assert result["verdict"] == "green"
        assert result["total"] == 3
        assert result["pass"] == 3
        assert result["pending"] == 0

    def test_any_pending_returns_pending(self):
        checks = [
            {"name": "build", "bucket": "pass"},
            {"name": "test", "bucket": "pending"},
            {"name": "lint", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "pending"
        assert result["pass"] == 2
        assert result["pending"] == 1

    def test_any_failing_returns_failing(self):
        checks = [
            {"name": "build", "bucket": "pass"},
            {"name": "test", "bucket": "fail"},
            {"name": "lint", "bucket": "pending"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "failing"
        assert result["fail"] == 1

    def test_failing_takes_priority_over_pending(self):
        checks = [
            {"name": "build", "bucket": "fail"},
            {"name": "test", "bucket": "pending"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "failing"

    def test_skipping_excluded_from_pass_count(self):
        checks = [
            {"name": "build", "bucket": "pass"},
            {"name": "optional", "bucket": "skipping"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "green"
        assert result["pass"] == 1
        assert result["skipping"] == 1
        assert result["total"] == 2

    def test_only_skipping_returns_empty(self):
        checks = [
            {"name": "optional-1", "bucket": "skipping"},
            {"name": "optional-2", "bucket": "skipping"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "empty"
        assert result["skipping"] == 2

    def test_cancelled_checks_do_not_count_as_green(self):
        checks = [
            {"name": "build", "bucket": "cancel"},
            {"name": "test", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "pending"
        assert result["cancel"] == 1

    def test_checks_array_preserved_in_output(self):
        checks = [
            {"name": "build", "bucket": "pass", "state": "completed", "conclusion": "success"},
        ]
        result = compute_verdict(checks=checks)
        assert len(result["checks"]) == 1
        assert result["checks"][0]["name"] == "build"
        assert result["checks"][0]["bucket"] == "pass"

    def test_unknown_bucket_treated_as_pending(self):
        checks = [
            {"name": "build", "bucket": "unknown_state"},
            {"name": "test", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "pending"
        assert result["pending"] == 1

    def test_missing_bucket_field_treated_as_pending(self):
        checks = [
            {"name": "build"},
            {"name": "test", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "pending"
        assert result["pending"] == 1

    def test_mergeable_field_included_in_output(self):
        result = compute_verdict(checks=[], mergeable="MERGEABLE")
        assert result["mergeable"] == "MERGEABLE"

    def test_default_mergeable_is_unknown(self):
        result = compute_verdict(checks=[])
        assert result["mergeable"] == "UNKNOWN"

    def test_conflicting_overrides_green_checks(self):
        checks = [
            {"name": "build", "bucket": "pass"},
            {"name": "test", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks, mergeable="CONFLICTING")
        assert result["verdict"] == "conflicting"
        assert result["pass"] == 2

    def test_conflicting_overrides_failing_checks(self):
        checks = [
            {"name": "build", "bucket": "fail"},
        ]
        result = compute_verdict(checks=checks, mergeable="CONFLICTING")
        assert result["verdict"] == "conflicting"

    def test_conflicting_overrides_pending_checks(self):
        checks = [
            {"name": "build", "bucket": "pending"},
        ]
        result = compute_verdict(checks=checks, mergeable="CONFLICTING")
        assert result["verdict"] == "conflicting"

    def test_conflicting_with_empty_checks(self):
        result = compute_verdict(checks=[], mergeable="CONFLICTING")
        assert result["verdict"] == "conflicting"

    @pytest.mark.parametrize("mergeable", ["MERGEABLE", "UNKNOWN"])
    def test_non_conflicting_mergeable_does_not_affect_verdict(self, mergeable):
        checks = [{"name": "build", "bucket": "pass"}]
        result = compute_verdict(checks=checks, mergeable=mergeable)
        assert result["verdict"] == "green"


class TestRequiredVerdict:
    def test_default_required_verdict_empty_without_annotation(self):
        checks = [{"name": "build", "bucket": "pass"}]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "green"
        assert result["required_verdict"] == "empty"

    def test_advisory_failure_does_not_fail_required_verdict(self):
        checks = [
            {"name": "build", "bucket": "pass", "required": True},
            {"name": "lint-advisory", "bucket": "fail", "required": False},
        ]
        result = compute_verdict(checks=checks, mergeable="MERGEABLE")
        assert result["verdict"] == "failing"
        assert result["required_verdict"] == "green"

    def test_required_failure_fails_required_verdict(self):
        checks = [
            {"name": "build", "bucket": "fail", "required": True},
            {"name": "lint-advisory", "bucket": "pass", "required": False},
        ]
        result = compute_verdict(checks=checks)
        assert result["verdict"] == "failing"
        assert result["required_verdict"] == "failing"

    def test_required_pending_advisory_green(self):
        checks = [
            {"name": "build", "bucket": "pending", "required": True},
            {"name": "lint-advisory", "bucket": "pass", "required": False},
        ]
        result = compute_verdict(checks=checks)
        assert result["required_verdict"] == "pending"

    def test_per_check_required_flag_in_output(self):
        checks = [
            {"name": "build", "bucket": "pass", "required": True},
            {"name": "lint", "bucket": "pass"},
        ]
        result = compute_verdict(checks=checks)
        assert result["checks"][0]["required"] is True
        assert result["checks"][1]["required"] is False

    def test_conflicting_sets_both_verdicts(self):
        checks = [{"name": "build", "bucket": "pass", "required": True}]
        result = compute_verdict(checks=checks, mergeable="CONFLICTING")
        assert result["verdict"] == "conflicting"
        assert result["required_verdict"] == "conflicting"


class TestGetRequiredNames:
    def _stub(self, *, returncode, stdout):
        class _R:
            pass

        r = _R()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = ""
        return r

    def test_parses_required_names(self, monkeypatch):
        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: self._stub(
                returncode=0, stdout='[{"name": "build"}, {"name": "test"}]'
            ),
        )
        assert _mod.get_required_names(pr_number=1, repo="o/r") == {"build", "test"}

    def test_nonzero_exit_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: self._stub(returncode=1, stdout=""),
        )
        assert _mod.get_required_names(pr_number=1, repo="o/r") == set()

    def test_blank_stdout_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: self._stub(returncode=0, stdout="   "),
        )
        assert _mod.get_required_names(pr_number=1, repo="o/r") == set()

    def test_unparseable_stdout_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            _mod.subprocess,
            "run",
            lambda *a, **k: self._stub(returncode=0, stdout="not json"),
        )
        assert _mod.get_required_names(pr_number=1, repo="o/r") == set()


class TestGetAnnotatedChecks:
    def test_required_only_marks_all_required(self, monkeypatch):
        monkeypatch.setattr(
            _impl,
            "get_checks",
            lambda **k: [{"name": "build", "bucket": "pass"}],
        )
        checks = _impl.get_annotated_checks(pr_number=1, repo="o/r", required_only=True)
        assert checks[0]["required"] is True

    def test_annotates_required_by_name(self, monkeypatch):
        monkeypatch.setattr(
            _impl,
            "get_checks",
            lambda **k: [
                {"name": "build", "bucket": "pass"},
                {"name": "lint", "bucket": "pass"},
            ],
        )
        monkeypatch.setattr(_impl, "get_required_names", lambda **k: {"build"})
        checks = _impl.get_annotated_checks(pr_number=1, repo="o/r")
        by_name = {c["name"]: c["required"] for c in checks}
        assert by_name == {"build": True, "lint": False}


class TestGetChecksError:
    def test_error_json_written_to_stdout_then_exits(self, monkeypatch, capsys):
        class _Failed:
            returncode = 1
            stderr = "rate limited"
            stdout = ""

        monkeypatch.setattr(_mod.subprocess, "run", lambda *a, **k: _Failed())
        with pytest.raises(SystemExit) as exc:
            _mod.get_checks(pr_number=42, repo="org/repo")
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert '"error"' in captured.out
        assert "rate limited" in captured.out
        assert captured.err == ""
