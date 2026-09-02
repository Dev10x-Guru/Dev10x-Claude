"""PostToolUse formatter stays inside the edit (GH-1143)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.hooks.format_scope import (
    LineRange,
    describe_changes,
    edited_range,
    resolve_format_policy,
)
from dev10x.hooks.skill import RuffFormatHook

_REVERT_SUBJECT = """from datetime import (
    datetime,
    timezone,
)


def started_at():
    return datetime.now(timezone.utc)
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 99\n")
    return tmp_path


class TestFormatPolicy:
    def test_ruff_configured_project_is_formatted(self, project: Path):
        plan = resolve_format_policy(project / "mod.py")
        assert plan.should_format is True
        assert plan.line_length is None  # ruff discovers its own config

    def test_black_line_length_is_honoured(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[tool.black]\nline-length = 99\n")
        plan = resolve_format_policy(tmp_path / "mod.py")
        assert plan.should_format is True
        assert plan.line_length == 99

    def test_flake8_max_line_length_is_honoured(self, tmp_path: Path):
        (tmp_path / "setup.cfg").write_text("[flake8]\nmax-line-length = 120\n")
        plan = resolve_format_policy(tmp_path / "mod.py")
        assert plan.line_length == 120

    def test_precommit_project_without_ruff_config_is_left_alone(self, tmp_path: Path):
        """tt-e2e passes its own pre-commit on the forms this hook rewrote."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        plan = resolve_format_policy(tmp_path / "mod.py")
        assert plan.should_format is False
        assert "pre-commit" in plan.skip_reason

    def test_malformed_pyproject_does_not_block_formatting(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[tool.ruff\nbroken")
        assert resolve_format_policy(tmp_path / "mod.py").should_format is True

    def test_file_outside_any_project_is_formatted(self, tmp_path: Path):
        assert resolve_format_policy(tmp_path / "loose.py").should_format is True

    def test_non_numeric_max_line_length_is_ignored(self, tmp_path: Path):
        (tmp_path / "setup.cfg").write_text("[flake8]\nmax-line-length = wide\n")
        assert resolve_format_policy(tmp_path / "mod.py").line_length is None

    def test_unreadable_flake8_config_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "setup.cfg").write_text("[flake8]\nmax-line-length = 120\n")

        def boom(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", boom)
        assert resolve_format_policy(tmp_path / "mod.py").line_length is None


class TestEditedRange:
    def test_single_edit_locates_its_new_string(self):
        span = edited_range(
            tool_input={"new_string": "def started_at():"},
            content=_REVERT_SUBJECT,
        )
        assert span == LineRange(start=7, end=7)

    def test_multiline_edit_spans_its_whole_replacement(self):
        span = edited_range(
            tool_input={"new_string": "from datetime import (\n    datetime,"},
            content=_REVERT_SUBJECT,
        )
        assert span == LineRange(start=1, end=2)

    def test_multi_edit_spans_min_to_max(self):
        span = edited_range(
            tool_input={
                "edits": [
                    {"new_string": "    datetime,"},
                    {"new_string": "    return datetime.now(timezone.utc)"},
                ]
            },
            content=_REVERT_SUBJECT,
        )
        assert span == LineRange(start=2, end=8)

    def test_multi_edit_with_no_locatable_span_falls_back(self):
        span = edited_range(
            tool_input={"edits": [{"new_string": "absent"}, {"other": "shape"}]},
            content=_REVERT_SUBJECT,
        )
        assert span is None

    def test_write_has_no_narrower_scope(self):
        assert edited_range(tool_input={"content": "x = 1"}, content="x = 1") is None

    def test_unlocatable_edit_falls_back_to_whole_file(self):
        assert edited_range(tool_input={"new_string": "absent"}, content="x = 1") is None

    def test_as_ruff_arg_is_inclusive_span(self):
        assert LineRange(start=3, end=9).as_ruff_arg() == "3-9"


class TestChangeDescription:
    def test_no_change_is_silent(self):
        assert describe_changes(before="x = 1\n", after="x = 1\n") == ""

    def test_names_the_changed_lines(self):
        summary = describe_changes(before="x=1\ny = 2\n", after="x = 1\ny = 2\n")
        assert "line(s) 1" in summary

    def test_reports_removed_lines(self):
        """The import-stripping case: a removed line must be named, not hidden."""
        summary = describe_changes(before="import os\nx = 1\n", after="x = 1\n")
        assert "removed 1 line(s)" in summary


class TestHookBehaviour:
    def test_lint_fixes_are_not_applied(self, project: Path, monkeypatch: pytest.MonkeyPatch):
        """`ruff check --fix` is what deleted a still-referenced import."""
        calls: list[list[str]] = []

        def record(args, **kwargs):
            calls.append(list(args))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("dev10x.hooks.skill.subprocess_utils.run", record)
        target = project / "mod.py"
        target.write_text(_REVERT_SUBJECT)

        RuffFormatHook().handle(
            data={"tool_input": {"file_path": str(target), "new_string": "def started_at():"}}
        )

        assert calls, "the formatter did not run"
        assert not any("check" in call for call in calls)
        assert all(call[:2] == ["ruff", "format"] for call in calls)

    def test_edit_is_formatted_with_a_range(self, project: Path, monkeypatch: pytest.MonkeyPatch):
        calls: list[list[str]] = []

        def record(args, **kwargs):
            calls.append(list(args))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("dev10x.hooks.skill.subprocess_utils.run", record)
        target = project / "mod.py"
        target.write_text(_REVERT_SUBJECT)

        RuffFormatHook().handle(
            data={"tool_input": {"file_path": str(target), "new_string": "def started_at():"}}
        )

        assert "--range" in calls[0]
        assert "7-7" in calls[0]

    def test_range_rejection_retries_whole_file(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A project pinning ruff < 0.9 must still get formatted."""
        calls: list[list[str]] = []

        def record(args, **kwargs):
            calls.append(list(args))
            failed = "--range" in args
            return type("R", (), {"returncode": 2 if failed else 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("dev10x.hooks.skill.subprocess_utils.run", record)
        target = project / "mod.py"
        target.write_text(_REVERT_SUBJECT)

        RuffFormatHook().handle(
            data={"tool_input": {"file_path": str(target), "new_string": "def started_at():"}}
        )

        assert len(calls) == 2
        assert "--range" not in calls[1]

    def test_precommit_project_is_skipped_with_a_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        calls: list[list[str]] = []
        monkeypatch.setattr(
            "dev10x.hooks.skill.subprocess_utils.run",
            lambda args, **kwargs: calls.append(list(args)),
        )
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        target = tmp_path / "mod.py"
        target.write_text("x = 1\n")

        RuffFormatHook().handle(data={"tool_input": {"file_path": str(target)}})

        assert calls == []
        assert "skipped" in json.loads(capsys.readouterr().out)["systemMessage"]

    def test_non_python_file_is_ignored(self, project: Path):
        target = project / "notes.md"
        target.write_text("# hi\n")
        with pytest.raises(SystemExit):
            RuffFormatHook().handle(data={"tool_input": {"file_path": str(target)}})
