"""Tests for SpecDriftValidator (DX015).

Covers:
- should_run() fast-skip for non-Edit/Write tools
- should_run() skip when editing the spec file itself
- validate() skips when no spec exists (no docs/specs/ in repo)
- validate() skips when branch has no ticket ID
- validate() skips when spec is already in working set
- validate() returns HookResult when spec exists but untouched
- Message format: references DX015, spec path, ticket ID, skill
- Registry integration: DX015 in standard profile only with experimental flag
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from dev10x.domain import HookInput
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators import get_validators, reset_registry
from dev10x.validators.spec_drift import (
    SpecDriftValidator,
    _branch_ticket_id,
    _repo_toplevel,
    _working_set_paths,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# GH-495: spec_drift now routes git calls through subprocess_utils.run
# (CWD-discipline). Patch that seam instead of subprocess.check_output.
_RUN = "dev10x.validators.spec_drift.subprocess_utils.run"


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    """Build a successful CompletedProcess mirroring subprocess_utils.run."""
    return subprocess.CompletedProcess(args=["git"], returncode=0, stdout=stdout, stderr="")


def _edit_inp(
    *,
    file_path: str = "/work/repo/src/foo.py",
    tool_name: str = "Edit",
    cwd: str = "/work/repo",
) -> HookInput:
    raw: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_input": {
            "file_path": file_path,
            "old_string": "before",
            "new_string": "after",
        },
    }
    return HookInput(
        tool_name=tool_name,
        command="",
        raw=raw,
        cwd=cwd,
    )


@pytest.fixture()
def validator() -> SpecDriftValidator:
    return SpecDriftValidator()


# ---------------------------------------------------------------------------
# should_run
# ---------------------------------------------------------------------------


class TestShouldRun:
    def test_bash_tool_skipped(self, validator: SpecDriftValidator) -> None:
        inp = HookInput(
            tool_name="Bash",
            command="ls -la",
            raw={"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        )
        assert validator.should_run(inp=inp) is False

    def test_read_tool_skipped(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp(tool_name="Read")
        assert validator.should_run(inp=inp) is False

    def test_edit_tool_runs(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp(tool_name="Edit")
        assert validator.should_run(inp=inp) is True

    def test_write_tool_runs(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp(tool_name="Write", file_path="/work/repo/src/new_module.py")
        assert validator.should_run(inp=inp) is True

    def test_editing_spec_file_skipped(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp(file_path="/work/repo/docs/specs/GH-434.md")
        assert validator.should_run(inp=inp) is False

    def test_empty_file_path_skipped(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp(file_path="")
        assert validator.should_run(inp=inp) is False

    def test_spec_subdir_in_path_skipped(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp(file_path="/work/repo/docs/specs/FEAT-123.md")
        assert validator.should_run(inp=inp) is False


# ---------------------------------------------------------------------------
# _branch_ticket_id
# ---------------------------------------------------------------------------


class TestBranchTicketId:
    def test_extracts_gh_ticket(self) -> None:
        with patch(_RUN, return_value=_completed("janusz/GH-434/feature\n")):
            result = _branch_ticket_id(cwd="/work/repo")
        assert result == "GH-434"

    def test_extracts_feat_ticket(self) -> None:
        with patch(_RUN, return_value=_completed("user/FEAT-123/something\n")):
            result = _branch_ticket_id(cwd="/work/repo")
        assert result == "FEAT-123"

    def test_returns_none_for_no_ticket(self) -> None:
        with patch(_RUN, return_value=_completed("main\n")):
            result = _branch_ticket_id(cwd="/work/repo")
        assert result is None

    def test_returns_none_on_git_error(self) -> None:
        with patch(
            _RUN,
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            result = _branch_ticket_id(cwd="/work/repo")
        assert result is None

    def test_returns_none_when_git_missing(self) -> None:
        with patch(_RUN, side_effect=FileNotFoundError()):
            result = _branch_ticket_id(cwd="/work/repo")
        assert result is None

    def test_uppercases_ticket_id(self) -> None:
        with patch(_RUN, return_value=_completed("user/gh-434/feature\n")):
            result = _branch_ticket_id(cwd="/work/repo")
        assert result == "GH-434"


# ---------------------------------------------------------------------------
# _repo_toplevel
# ---------------------------------------------------------------------------


class TestRepoToplevel:
    def test_returns_toplevel(self) -> None:
        with patch(_RUN, return_value=_completed("/work/repo\n")):
            result = _repo_toplevel(cwd="/work/repo")
        assert result == "/work/repo"

    def test_returns_none_on_error(self) -> None:
        with patch(
            _RUN,
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            result = _repo_toplevel(cwd="/some/path")
        assert result is None


# ---------------------------------------------------------------------------
# _working_set_paths
# ---------------------------------------------------------------------------


class TestWorkingSetPaths:
    def test_parses_modified_file(self) -> None:
        with patch(_RUN, return_value=_completed(" M docs/specs/GH-434.md\n")):
            paths = _working_set_paths(cwd="/work/repo")
        assert "docs/specs/GH-434.md" in paths

    def test_parses_added_file(self) -> None:
        with patch(_RUN, return_value=_completed("A  docs/specs/NEW-1.md\n")):
            paths = _working_set_paths(cwd="/work/repo")
        assert "docs/specs/NEW-1.md" in paths

    def test_parses_rename(self) -> None:
        with patch(
            _RUN,
            return_value=_completed("R  old/path.md -> new/path.md\n"),
        ):
            paths = _working_set_paths(cwd="/work/repo")
        assert "new/path.md" in paths

    def test_returns_empty_on_git_error(self) -> None:
        with patch(
            _RUN,
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            paths = _working_set_paths(cwd="/work/repo")
        assert paths == set()

    def test_returns_empty_when_git_missing(self) -> None:
        with patch(_RUN, side_effect=FileNotFoundError()):
            paths = _working_set_paths(cwd="/work/repo")
        assert paths == set()


# ---------------------------------------------------------------------------
# validate() — full integration with mocks
# ---------------------------------------------------------------------------


class TestValidate:
    def test_returns_none_when_no_ticket_id(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp()
        with patch(
            "dev10x.validators.spec_drift._branch_ticket_id",
            return_value=None,
        ):
            result = validator.validate(inp=inp)
        assert result is None

    def test_returns_none_when_no_repo_toplevel(self, validator: SpecDriftValidator) -> None:
        inp = _edit_inp()
        with (
            patch(
                "dev10x.validators.spec_drift._branch_ticket_id",
                return_value="GH-434",
            ),
            patch(
                "dev10x.validators.spec_drift._repo_toplevel",
                return_value=None,
            ),
        ):
            result = validator.validate(inp=inp)
        assert result is None

    def test_returns_none_when_spec_missing(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        inp = _edit_inp(cwd=str(tmp_path))
        with (
            patch(
                "dev10x.validators.spec_drift._branch_ticket_id",
                return_value="GH-434",
            ),
            patch(
                "dev10x.validators.spec_drift._repo_toplevel",
                return_value=str(tmp_path),
            ),
            patch(
                "dev10x.validators.spec_drift._working_set_paths",
                return_value=set(),
            ),
        ):
            result = validator.validate(inp=inp)
        assert result is None

    def test_returns_none_when_spec_in_working_set(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "GH-434.md").write_text("# GH-434 spec")
        inp = _edit_inp(cwd=str(tmp_path))
        with (
            patch(
                "dev10x.validators.spec_drift._branch_ticket_id",
                return_value="GH-434",
            ),
            patch(
                "dev10x.validators.spec_drift._repo_toplevel",
                return_value=str(tmp_path),
            ),
            patch(
                "dev10x.validators.spec_drift._working_set_paths",
                return_value={"docs/specs/GH-434.md"},
            ),
        ):
            result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_when_spec_exists_and_untouched(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "GH-434.md").write_text("# GH-434 spec")
        inp = _edit_inp(file_path="/work/repo/src/validators/spec_drift.py", cwd=str(tmp_path))
        with (
            patch(
                "dev10x.validators.spec_drift._branch_ticket_id",
                return_value="GH-434",
            ),
            patch(
                "dev10x.validators.spec_drift._repo_toplevel",
                return_value=str(tmp_path),
            ),
            patch(
                "dev10x.validators.spec_drift._working_set_paths",
                return_value={"src/validators/spec_drift.py"},
            ),
        ):
            result = validator.validate(inp=inp)
        assert result is not None

    def test_write_tool_also_blocked(self, validator: SpecDriftValidator, tmp_path: Path) -> None:
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "FEAT-999.md").write_text("# FEAT-999 spec")
        inp = _edit_inp(
            file_path="/work/repo/src/new_module.py",
            tool_name="Write",
            cwd=str(tmp_path),
        )
        with (
            patch(
                "dev10x.validators.spec_drift._branch_ticket_id",
                return_value="FEAT-999",
            ),
            patch(
                "dev10x.validators.spec_drift._repo_toplevel",
                return_value=str(tmp_path),
            ),
            patch(
                "dev10x.validators.spec_drift._working_set_paths",
                return_value=set(),
            ),
        ):
            result = validator.validate(inp=inp)
        assert result is not None


# ---------------------------------------------------------------------------
# Message format
# ---------------------------------------------------------------------------


class TestMessageFormat:
    def _blocked_result(
        self,
        validator: SpecDriftValidator,
        tmp_path: Path,
        ticket_id: str = "GH-434",
    ):
        spec_dir = tmp_path / "docs" / "specs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / f"{ticket_id}.md").write_text(f"# {ticket_id} spec")
        inp = _edit_inp(file_path="/work/repo/src/foo.py", cwd=str(tmp_path))
        with (
            patch(
                "dev10x.validators.spec_drift._branch_ticket_id",
                return_value=ticket_id,
            ),
            patch(
                "dev10x.validators.spec_drift._repo_toplevel",
                return_value=str(tmp_path),
            ),
            patch(
                "dev10x.validators.spec_drift._working_set_paths",
                return_value=set(),
            ),
        ):
            return validator.validate(inp=inp)

    def test_message_contains_rule_id(self, validator: SpecDriftValidator, tmp_path: Path) -> None:
        result = self._blocked_result(validator, tmp_path)
        assert result is not None
        assert "DX015" in result.message

    def test_message_contains_ticket_id(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        result = self._blocked_result(validator, tmp_path)
        assert result is not None
        assert "GH-434" in result.message

    def test_message_contains_spec_path(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        result = self._blocked_result(validator, tmp_path)
        assert result is not None
        assert "docs/specs/GH-434.md" in result.message

    def test_message_references_spec_update_skill(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        result = self._blocked_result(validator, tmp_path)
        assert result is not None
        assert "spec-update" in result.message

    def test_message_references_hook_patterns(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        result = self._blocked_result(validator, tmp_path)
        assert result is not None
        assert "hook-patterns.md" in result.message

    def test_message_contains_edited_file_path(
        self, validator: SpecDriftValidator, tmp_path: Path
    ) -> None:
        result = self._blocked_result(validator, tmp_path)
        assert result is not None
        assert "/work/repo/src/foo.py" in result.message


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry():
    reset_registry()
    yield
    reset_registry()


class TestRegistryIntegration:
    def test_dx015_absent_in_standard_without_experimental(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEV10X_HOOK_PROFILE", raising=False)
        monkeypatch.delenv("DEV10X_HOOK_EXPERIMENTAL", raising=False)
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX015" not in rule_ids

    def test_dx015_present_in_standard_with_experimental(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEV10X_HOOK_PROFILE", raising=False)
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", "1")
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX015" in rule_ids

    def test_dx015_absent_in_minimal_even_with_experimental(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "minimal")
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", "1")
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX015" not in rule_ids

    def test_dx015_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", "1")
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX015")
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX015" not in rule_ids

    def test_validator_instance_is_spec_drift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", "1")
        validators = get_validators()
        spec_drift_validators = [v for v in validators if v.rule_id == "DX015"]
        assert len(spec_drift_validators) == 1
        assert isinstance(spec_drift_validators[0], SpecDriftValidator)

    def test_validator_profile_is_standard(self) -> None:
        v = SpecDriftValidator()
        assert v.profile is ProfileTier.STANDARD

    def test_validator_is_experimental(self) -> None:
        v = SpecDriftValidator()
        assert v.experimental is True

    def test_rule_ids_remain_unique(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "strict")
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", "1")
        validators = get_validators()
        rule_ids = [v.rule_id for v in validators]
        assert len(rule_ids) == len(set(rule_ids)), f"Duplicate rule_ids: {rule_ids}"
