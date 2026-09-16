"""Tests for the stranded-work detector (GH-1363)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.orchestration import orchestration
from dev10x.skills.orchestration.stranded_work import (
    StrandedSignal,
    StrandedVerdict,
    decide_stranded_work,
    inspect_worktree,
    parse_porcelain,
    resume_prompt,
)
from dev10x.skills.orchestration.subagent_protocol import SubagentStatus


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    repo = tmp_path / "agent-worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


@pytest.fixture
def dirty_worktree(git_worktree: Path) -> Path:
    (git_worktree / "stop_verdict.py").write_text("uncommitted\n")
    return git_worktree


class TestParsePorcelain:
    @pytest.mark.parametrize(
        ("porcelain", "expected"),
        [
            ("", ()),
            ("\n  \n", ()),
            (" M src/dev10x/hooks/stop_verdict.py\n", ("src/dev10x/hooks/stop_verdict.py",)),
            (
                "?? tests/test_stop_verdict_open_work.py\n",
                ("tests/test_stop_verdict_open_work.py",),
            ),
            ("R  old.py -> new.py\n", ("new.py",)),
            (" M a.py\n?? b.py\n", ("a.py", "b.py")),
        ],
    )
    def test_paths_extracted(self, porcelain: str, expected: tuple[str, ...]):
        assert parse_porcelain(porcelain=porcelain) == expected


class TestDecideStrandedWork:
    def test_clean_worktree_never_triggers_a_resume(self):
        verdict = decide_stranded_work(porcelain="", status=SubagentStatus.DONE)

        assert verdict.signal is StrandedSignal.CLEAN
        assert verdict.resume_required is False
        assert verdict.teardown_allowed is True
        assert verdict.paths == ()

    def test_dirty_worktree_strands_even_on_done(self):
        verdict = decide_stranded_work(
            porcelain=" M stop_verdict.py\n?? test_open_work.py\n",
            status=SubagentStatus.DONE,
        )

        assert verdict.signal is StrandedSignal.STRANDED
        assert verdict.resume_required is True
        assert verdict.teardown_allowed is False
        assert verdict.paths == ("stop_verdict.py", "test_open_work.py")
        assert "2 uncommitted path(s) after DONE" in verdict.reason

    def test_dirty_worktree_strands_on_needs_context(self):
        verdict = decide_stranded_work(
            porcelain=" M a.py\n",
            status=SubagentStatus.NEEDS_CONTEXT,
        )

        assert verdict.resume_required is True
        assert "NEEDS_CONTEXT" in verdict.reason

    def test_missing_worktree_is_unreachable_not_stranded(self):
        verdict = decide_stranded_work(
            porcelain="",
            status=SubagentStatus.DONE,
            worktree_exists=False,
        )

        assert verdict.signal is StrandedSignal.UNREACHABLE
        assert verdict.resume_required is False
        assert verdict.teardown_allowed is False

    def test_clean_reason_names_the_status(self):
        verdict = decide_stranded_work(porcelain="", status=SubagentStatus.BLOCKED)

        assert verdict.reason == "worktree clean after BLOCKED"


class TestVerdictSerialization:
    def test_to_dict_carries_every_field(self):
        verdict = StrandedVerdict(
            signal=StrandedSignal.STRANDED,
            paths=("a.py",),
            reason="because",
        )

        assert verdict.to_dict() == {
            "signal": "stranded",
            "paths": ["a.py"],
            "reason": "because",
            "resume_required": True,
            "teardown_allowed": False,
        }


class TestResumePrompt:
    def test_stranded_prompt_names_the_paths_and_the_ordering(self):
        verdict = decide_stranded_work(porcelain=" M a.py\n", status=SubagentStatus.DONE)

        prompt = resume_prompt(verdict=verdict)

        assert "a.py" in prompt
        assert "before any verification step" in prompt

    def test_clean_verdict_has_no_prompt(self):
        verdict = decide_stranded_work(porcelain="", status=SubagentStatus.DONE)

        assert resume_prompt(verdict=verdict) == ""


class TestInspectWorktree:
    def test_clean_repo_reports_clean(self, git_worktree: Path):
        verdict = inspect_worktree(worktree=git_worktree, status=SubagentStatus.DONE)

        assert verdict.signal is StrandedSignal.CLEAN

    def test_untracked_file_is_detected(self, dirty_worktree: Path):
        verdict = inspect_worktree(worktree=dirty_worktree, status=SubagentStatus.DONE)

        assert verdict.signal is StrandedSignal.STRANDED
        assert verdict.paths == ("stop_verdict.py",)

    def test_absent_path_reports_unreachable(self, tmp_path: Path):
        verdict = inspect_worktree(
            worktree=tmp_path / "reclaimed",
            status=SubagentStatus.DONE,
        )

        assert verdict.signal is StrandedSignal.UNREACHABLE

    def test_non_repository_reports_unreachable(self, tmp_path: Path):
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()

        verdict = inspect_worktree(worktree=not_a_repo, status=SubagentStatus.DONE)

        assert verdict.signal is StrandedSignal.UNREACHABLE
        assert verdict.reason


class TestStrandedWorkCommand:
    def test_clean_worktree_exits_zero(self, git_worktree: Path):
        result = CliRunner().invoke(orchestration, ["stranded-work", str(git_worktree)])

        assert result.exit_code == 0
        assert '"signal": "clean"' in result.output

    def test_dirty_worktree_exits_one_with_a_resume_prompt(self, dirty_worktree: Path):
        result = CliRunner().invoke(
            orchestration,
            ["stranded-work", str(dirty_worktree), "--status", "DONE"],
        )

        assert result.exit_code == 1
        assert '"resume_required": true' in result.output
        assert "stop_verdict.py" in result.output
