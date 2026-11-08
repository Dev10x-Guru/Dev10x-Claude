from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.review_stamp import ReviewStamp, ReviewStampStore
from dev10x.validators.review_stamp import ReviewStampValidator

from dev10x.domain import HookInput, HookResult
from dev10x.validators import get_registry, reset_registry
from tests.fakers.process import completed as _completed

_RUN = "dev10x.validators.review_stamp.subprocess_utils.run"
MERGE = "mcp__plugin_dev10x_cli__merge_pr"
READY = "mcp__plugin_dev10x_cli__pr_ready"
REVIEW = "mcp__plugin_dev10x_cli__request_review"
SLUG = "Dev10x-Guru/Dev10x-Claude"
HEAD = "a" * 40
TREE = "t" * 40
PR_URL = f"https://github.com/{SLUG}/pull/42"


def _gh_payload(*, sha: str = HEAD, branch: str = "feature", url: str = PR_URL) -> str:
    return json.dumps({"headRefOid": sha, "headRefName": branch, "url": url})


def _inp(*, tool: str = MERGE, cwd: str = "", **tool_input: Any) -> HookInput:
    return HookInput(
        tool_name=tool,
        command="",
        raw={"tool_name": tool, "tool_input": tool_input},
        cwd=cwd,
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "Dev10x-Claude"
    (repo / "src").mkdir(parents=True)
    (repo / ".git").mkdir()
    return repo


@pytest.fixture
def required(checkout: Path) -> None:
    friction = Dev10xConfigDir.friction_yaml()
    friction.parent.mkdir(parents=True, exist_ok=True)
    friction.write_text(
        yaml.safe_dump(
            {"projects": [{"match": [f"*/{checkout.name}"], "review_stamp": "required"}]}
        )
    )


@pytest.fixture
def store() -> ReviewStampStore:
    return ReviewStampStore(path=Dev10xConfigDir.review_stamps_json())


@pytest.fixture
def validator() -> ReviewStampValidator:
    return ReviewStampValidator()


def _stamp(*, store: ReviewStampStore, head_sha: str = HEAD, tree_sha: str = TREE) -> None:
    store.write(
        slug=SLUG.casefold(),
        branch="feature",
        stamp=ReviewStamp(head_sha=head_sha, tree_sha=tree_sha, reviewed_at="now"),
    )


def _run_with(*, gh_stdout: str, tree_stdout: str = TREE):
    def fake(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        if command[0] == "gh":
            return _completed(stdout=gh_stdout)
        return _completed(stdout=tree_stdout)

    return fake


class TestShouldRun:
    @pytest.mark.parametrize("tool", [MERGE, READY, REVIEW])
    def test_gated_tools_run(self, validator: ReviewStampValidator, tool: str) -> None:
        assert validator.should_run(inp=_inp(tool=tool, pr_number=1)) is True

    @pytest.mark.parametrize(
        "tool", ["Bash", "mcp__plugin_dev10x_cli__pr_get", "mcp__plugin_other__merge_pr"]
    )
    def test_other_tools_skip(self, validator: ReviewStampValidator, tool: str) -> None:
        assert validator.should_run(inp=_inp(tool=tool, pr_number=1)) is False

    def test_pr_ready_undo_skips(self, validator: ReviewStampValidator) -> None:
        assert validator.should_run(inp=_inp(tool=READY, pr_number=1, undo=True)) is False

    def test_merge_with_undo_flag_still_runs(self, validator: ReviewStampValidator) -> None:
        assert validator.should_run(inp=_inp(tool=MERGE, pr_number=1, undo=True)) is True


class TestGateScope:
    def test_no_checkout_abstains(self, validator: ReviewStampValidator) -> None:
        assert validator.validate(inp=_inp(pr_number=1)) is None

    def test_cwd_outside_any_repo_abstains(
        self, validator: ReviewStampValidator, tmp_path: Path
    ) -> None:
        assert validator.validate(inp=_inp(cwd=str(tmp_path), pr_number=1)) is None

    def test_repo_without_the_setting_abstains(
        self, validator: ReviewStampValidator, checkout: Path
    ) -> None:
        with patch(_RUN) as run:
            assert validator.validate(inp=_inp(cwd=str(checkout), pr_number=1)) is None
        run.assert_not_called()

    @pytest.mark.usefixtures("required")
    def test_absolute_tool_input_cwd_wins_over_hook_cwd(
        self, validator: ReviewStampValidator, checkout: Path, tmp_path: Path
    ) -> None:
        inp = HookInput(
            tool_name=MERGE,
            command="",
            raw={"tool_input": {"pr_number": 42, "cwd": str(checkout)}},
            cwd=str(tmp_path),
        )
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())) as run:
            result = validator.validate(inp=inp)

        assert isinstance(result, HookResult)
        assert run.call_args_list[0].kwargs["cwd"] == str(checkout)

    @pytest.mark.usefixtures("required")
    def test_non_repo_tool_cwd_cannot_lift_the_session_gate(
        self, validator: ReviewStampValidator, checkout: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        inp = HookInput(
            tool_name=MERGE,
            command="",
            raw={"tool_input": {"pr_number": 42, "cwd": str(outside)}},
            cwd=str(checkout),
        )
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())) as run:
            result = validator.validate(inp=inp)

        assert isinstance(result, HookResult)
        assert "has no review stamp" in result.message
        assert run.call_args_list[0].kwargs["cwd"] == str(checkout)

    @pytest.mark.usefixtures("required")
    def test_ungated_tool_repo_cannot_lift_the_session_gate(
        self, validator: ReviewStampValidator, checkout: Path, tmp_path: Path
    ) -> None:
        ungated = tmp_path / "ungated-repo"
        (ungated / ".git").mkdir(parents=True)
        inp = HookInput(
            tool_name=MERGE,
            command="",
            raw={"tool_input": {"pr_number": 42, "cwd": str(ungated)}},
            cwd=str(checkout),
        )
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())) as run:
            result = validator.validate(inp=inp)

        assert isinstance(result, HookResult)
        assert run.call_args_list[0].kwargs["cwd"] == str(ungated)

    @pytest.mark.usefixtures("required")
    def test_relative_tool_input_cwd_falls_back_to_hook_cwd(
        self, validator: ReviewStampValidator, checkout: Path
    ) -> None:
        inp = HookInput(
            tool_name=MERGE,
            command="",
            raw={"tool_input": {"pr_number": 42, "cwd": "relative/dir"}},
            cwd=str(checkout / "src"),
        )
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())):
            assert isinstance(validator.validate(inp=inp), HookResult)


@pytest.mark.usefixtures("required")
class TestVerdicts:
    def test_missing_stamp_denies_with_head_and_hint(
        self, validator: ReviewStampValidator, checkout: Path
    ) -> None:
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "DX019" in result.message
        assert "has no review stamp" in result.message
        assert HEAD in result.message
        assert "dev10x:review --loop" in result.message

    def test_current_stamp_passes(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store)
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())):
            assert validator.validate(inp=_inp(cwd=str(checkout), pr_number=42)) is None

    def test_groomed_head_with_same_tree_passes(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store, head_sha="b" * 40)
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())):
            assert validator.validate(inp=_inp(cwd=str(checkout), pr_number=42)) is None

    def test_stale_stamp_names_both_shas(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store, head_sha="b" * 40, tree_sha="u" * 40)
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "b" * 40 in result.message
        assert HEAD in result.message
        assert "different content" in result.message

    def test_unresolvable_head_tree_needs_exact_commit(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store, head_sha="b" * 40)

        def fake(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            if command[0] == "gh":
                return _completed(stdout=_gh_payload())
            raise subprocess.CalledProcessError(returncode=1, cmd=command)

        with patch(_RUN, side_effect=fake):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "cannot compare" in result.message

    def test_stamp_of_another_branch_does_not_count(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store)
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload(branch="other"))):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "branch `other`) has no review stamp" in result.message

    def test_unexpected_error_denies(
        self, validator: ReviewStampValidator, checkout: Path
    ) -> None:
        with patch(
            "dev10x.validators.review_stamp.ReviewStampStore.read",
            side_effect=RuntimeError("boom"),
        ):
            with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())):
                result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "the review stamp check failed" in result.message


@pytest.mark.usefixtures("required")
class TestPrResolution:
    @pytest.mark.parametrize("pr_number", [None, "42", True])
    def test_missing_or_non_integer_pr_number_denies(
        self, validator: ReviewStampValidator, checkout: Path, pr_number: Any
    ) -> None:
        result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=pr_number))

        assert isinstance(result, HookResult)
        assert "pr_number" in result.message

    def test_repo_argument_is_passed_to_gh(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store)
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload())) as run:
            validator.validate(inp=_inp(cwd=str(checkout), pr_number=42, repo=SLUG))

        gh_command = run.call_args_list[0].args[0]
        assert gh_command[-2:] == ["--repo", SLUG]
        assert run.call_args_list[0].kwargs["cwd"] == str(checkout)

    def test_stamp_is_keyed_by_the_pr_url_repo(
        self, validator: ReviewStampValidator, checkout: Path, store: ReviewStampStore
    ) -> None:
        _stamp(store=store)
        other_url = "https://github.com/someone/fork/pull/42"
        with patch(_RUN, side_effect=_run_with(gh_stdout=_gh_payload(url=other_url))):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "(someone/fork, branch `feature`) has no review stamp" in result.message

    @pytest.mark.parametrize(
        "side_effect",
        [
            subprocess.CalledProcessError(returncode=1, cmd=["gh"]),
            subprocess.TimeoutExpired(cmd=["gh"], timeout=15),
            OSError("gh missing"),
        ],
    )
    def test_gh_failure_denies(
        self, validator: ReviewStampValidator, checkout: Path, side_effect: Exception
    ) -> None:
        with patch(_RUN, side_effect=side_effect):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "could not read the head of PR #42" in result.message

    @pytest.mark.parametrize(
        "stdout",
        [
            "not json",
            "[]",
            "null",
            json.dumps({"headRefOid": HEAD, "headRefName": "feature", "url": "nope"}),
            json.dumps({"headRefOid": "", "headRefName": "feature", "url": PR_URL}),
            json.dumps({"headRefOid": HEAD, "url": PR_URL}),
        ],
    )
    def test_unusable_gh_payload_denies(
        self, validator: ReviewStampValidator, checkout: Path, stdout: str
    ) -> None:
        with patch(_RUN, return_value=_completed(stdout=stdout)):
            result = validator.validate(inp=_inp(cwd=str(checkout), pr_number=42))

        assert isinstance(result, HookResult)
        assert "could not read the head of PR #42" in result.message


class TestRegistry:
    def test_dx019_is_active_at_the_standard_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEV10X_HOOK_PROFILE", raising=False)
        monkeypatch.delenv("DEV10X_HOOK_DISABLE", raising=False)
        reset_registry()

        assert get_registry().is_active("DX019") is True
        assert ReviewStampValidator.profile is ProfileTier.STANDARD

    def test_dx019_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX019")
        reset_registry()

        assert get_registry().is_active("DX019") is False
        reset_registry()
