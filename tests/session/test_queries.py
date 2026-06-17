"""Tests for SessionContextQuery — session-context assembly dataclass."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dev10x.domain.documents.session_context import (
    SessionContextQuery,
    format_compaction_summary,
    format_reload_context,
)
from dev10x.domain.friction_level import FrictionLevel


def _ctx(**kwargs: Any) -> SessionContextQuery:
    return SessionContextQuery(toplevel="/fake/root", **kwargs)


class TestSessionContextQueryDefaults:
    def test_branch_defaults_to_unknown(self) -> None:
        ctx = _ctx()
        assert ctx.branch == "unknown"

    def test_worktree_name_defaults_to_empty(self) -> None:
        ctx = _ctx()
        assert ctx.worktree_name == ""

    def test_state_defaults_to_empty_dict(self) -> None:
        ctx = _ctx()
        assert ctx.state == {}

    def test_plan_exists_defaults_to_false(self) -> None:
        ctx = _ctx()
        assert not ctx.plan_exists

    def test_file_lists_default_to_empty(self) -> None:
        ctx = _ctx()
        assert ctx.modified_files == []
        assert ctx.staged_files == []
        assert ctx.untracked_files == []

    def test_recent_commits_defaults_to_empty(self) -> None:
        ctx = _ctx()
        assert ctx.recent_commits == ""

    def test_is_frozen(self) -> None:
        ctx = _ctx()
        with pytest.raises(Exception):
            ctx.branch = "new-branch"  # type: ignore[misc]


class TestFormatReloadContext:
    def test_returns_empty_when_no_state_and_no_plan(self) -> None:
        ctx = _ctx(state={}, plan_exists=False)
        assert format_reload_context(ctx=ctx) == ""

    def test_returns_empty_with_empty_state(self) -> None:
        ctx = _ctx(state={}, plan_exists=False)
        assert format_reload_context(ctx=ctx) == ""


class TestFormatCompactionSummary:
    def test_includes_branch_in_output(self, tmp_path: Path) -> None:
        ctx = _ctx(branch="feature/some-work")
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "feature/some-work" in result

    def test_includes_toplevel_in_output(self, tmp_path: Path) -> None:
        ctx = _ctx()
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "/fake/root" in result

    def test_includes_worktree_when_set(self, tmp_path: Path) -> None:
        ctx = _ctx(worktree_name="Dev10x-Claude-8")
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "Dev10x-Claude-8" in result

    def test_omits_worktree_section_when_empty(self, tmp_path: Path) -> None:
        ctx = _ctx(worktree_name="")
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "Worktree" not in result

    def test_lists_modified_files(self, tmp_path: Path) -> None:
        ctx = _ctx(modified_files=["src/foo.py", "src/bar.py"])
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "src/foo.py" in result
        assert "src/bar.py" in result

    def test_lists_staged_files(self, tmp_path: Path) -> None:
        ctx = _ctx(staged_files=["src/baz.py"])
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "src/baz.py" in result

    def test_lists_untracked_files(self, tmp_path: Path) -> None:
        ctx = _ctx(untracked_files=["scratch.py"])
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "scratch.py" in result

    def test_includes_recent_commits(self, tmp_path: Path) -> None:
        ctx = _ctx(recent_commits="abc1234 Fix something\ndef5678 Add feature")
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "abc1234" in result

    def test_omits_file_sections_when_empty(self, tmp_path: Path) -> None:
        ctx = _ctx()
        result = format_compaction_summary(ctx=ctx, plugin_root=tmp_path)
        assert "Modified files" not in result
        assert "Staged files" not in result
        assert "Untracked files" not in result

    def test_returns_string(self, tmp_path: Path) -> None:
        ctx = _ctx()
        assert isinstance(format_compaction_summary(ctx=ctx, plugin_root=tmp_path), str)


class TestGatherReload:
    def test_returns_query_with_correct_toplevel(self, tmp_path: Path) -> None:
        with (
            patch("dev10x.domain.documents.session_context.claim_state_file", return_value={}),
            patch(
                "dev10x.domain.documents.session_context.state_path_for_toplevel",
                return_value=tmp_path / "state.json",
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_reload(toplevel=str(tmp_path))
        assert ctx.toplevel == str(tmp_path)

    def test_plan_exists_false_when_no_plan_file(self, tmp_path: Path) -> None:
        with (
            patch("dev10x.domain.documents.session_context.claim_state_file", return_value={}),
            patch(
                "dev10x.domain.documents.session_context.state_path_for_toplevel",
                return_value=tmp_path / "state.json",
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_reload(toplevel=str(tmp_path))
        assert not ctx.plan_exists

    def test_plan_exists_true_when_plan_file_present(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.json"
        plan_file.write_text("{}")
        with (
            patch("dev10x.domain.documents.session_context.claim_state_file", return_value={}),
            patch(
                "dev10x.domain.documents.session_context.state_path_for_toplevel",
                return_value=tmp_path / "state.json",
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=plan_file,
            ),
            patch(
                "dev10x.domain.documents.session_context.read_plan_summary",
                return_value={"tasks": []},
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_reload(toplevel=str(tmp_path))
        assert ctx.plan_exists

    def test_state_comes_from_claim_state_file(self, tmp_path: Path) -> None:
        fake_state = {"session_id": "test-123", "branch": "main"}
        with (
            patch(
                "dev10x.domain.documents.session_context.claim_state_file", return_value=fake_state
            ),
            patch(
                "dev10x.domain.documents.session_context.state_path_for_toplevel",
                return_value=tmp_path / "state.json",
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_reload(toplevel=str(tmp_path))
        assert ctx.state == fake_state


class TestGatherCompaction:
    def _mock_git(self, *, branch: str = "main", run_return: str = "") -> MagicMock:
        mock = MagicMock()
        mock.branch = branch
        mock.run.return_value = run_return
        return mock

    def test_returns_query_with_correct_toplevel(self, tmp_path: Path) -> None:
        with (
            patch(
                "dev10x.domain.documents.session_context.GitContext", return_value=self._mock_git()
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_compaction(toplevel=str(tmp_path))
        assert ctx.toplevel == str(tmp_path)

    def test_branch_comes_from_git_context(self, tmp_path: Path) -> None:
        with (
            patch(
                "dev10x.domain.documents.session_context.GitContext",
                return_value=self._mock_git(branch="feature/test"),
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_compaction(toplevel=str(tmp_path))
        assert ctx.branch == "feature/test"

    def test_worktree_name_empty_when_git_is_directory(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        with (
            patch(
                "dev10x.domain.documents.session_context.GitContext", return_value=self._mock_git()
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_compaction(toplevel=str(tmp_path))
        assert ctx.worktree_name == ""

    def test_worktree_name_set_when_git_is_file(self, tmp_path: Path) -> None:
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: ../../.git/worktrees/foo")
        with (
            patch(
                "dev10x.domain.documents.session_context.GitContext", return_value=self._mock_git()
            ),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_compaction(toplevel=str(tmp_path))
        assert ctx.worktree_name == tmp_path.name

    def test_git_error_yields_empty_files(self, tmp_path: Path) -> None:
        import subprocess

        mock_git = MagicMock()
        mock_git.branch = "main"
        mock_git.run.side_effect = subprocess.CalledProcessError(1, "git")
        with (
            patch("dev10x.domain.documents.session_context.GitContext", return_value=mock_git),
            patch(
                "dev10x.domain.documents.session_context.plan_path_for_toplevel",
                return_value=tmp_path / "plan.json",
            ),
            patch("dev10x.domain.documents.session_context.ReadFrictionLevelRule") as mock_rule,
        ):
            mock_rule.return_value.apply.return_value = FrictionLevel.default()
            ctx = SessionContextQuery.gather_compaction(toplevel=str(tmp_path))
        assert ctx.modified_files == []
        assert ctx.staged_files == []
        assert ctx.untracked_files == []
