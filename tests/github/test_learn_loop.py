"""Unit tests for dev10x.github.learn_loop (GH-353).

Contract class: mock
  ``render_pr_body`` is a pure function tested without mocks. The
  orchestrator patches the GH-349 author and the ``async_run`` chokepoint
  so no ``gh``/``git`` subprocess runs; rule docs are written under
  ``tmp_path``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok

ll = pytest.importorskip("dev10x.github.learn_loop", reason="dev10x not installed")


def _rule(*, slug: str = "block-chaining") -> dict:
    return {
        "slug": slug,
        "title": "Block chaining",
        "path": f"references/review-checks/generated/{slug}.md",
        "content": f"# Block chaining\n\nbody for {slug}\n",
    }


def _authored(*, rules: list[dict] | None = None) -> dict:
    return {
        "rules": rules if rules is not None else [_rule()],
        "routing_fragment": "| Generated rule | Reviewer agent |\n|---|---|",
        "summary": {"repos_scanned": ["o/r"], "rules_authored": len(rules or [_rule()])},
    }


def _cp(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestRenderPrBody:
    def test_lists_rules_routing_and_count(self) -> None:
        body = ll.render_pr_body(
            rules=[_rule(), _rule(slug="named-params")],
            routing_fragment="| Generated rule | Reviewer agent |",
            summary={"repos_scanned": ["o/r"]},
        )
        assert "mined **2**" in body
        assert "o/r" in body
        assert "`references/review-checks/generated/block-chaining.md`" in body
        assert "`references/review-checks/generated/named-params.md`" in body
        assert "### Routing" in body
        assert "| Generated rule | Reviewer agent |" in body

    def test_falls_back_to_this_repository_when_no_scan(self) -> None:
        body = ll.render_pr_body(rules=[_rule()], routing_fragment="x", summary={})
        assert "this repository" in body


class TestRunLearningLoopNoPr:
    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_no_rules_opens_no_pr(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored(rules=[]))

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, SuccessResult)
        assert result.value["opened_pr"] is False
        assert result.value["reason"] == "no validated review patterns"
        assert result.value["rules_authored"] == 0
        mock_run.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_propagates_author_error(self, mock_author: AsyncMock, tmp_path: Path) -> None:
        mock_author.return_value = err("no repository specified")

        result = await ll.run_learning_loop(base_dir=str(tmp_path))

        assert isinstance(result, ErrorResult)
        assert result.error == "no repository specified"

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_no_changes_reports_up_to_date(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        # checkout -B, add, then diff --cached --quiet returns 0 (no staged change).
        mock_run.side_effect = [_cp(0), _cp(0), _cp(0)]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, SuccessResult)
        assert result.value["opened_pr"] is False
        assert result.value["reason"] == "rules already up to date"
        assert result.value["rules_authored"] == 1


class TestRunLearningLoopHappyPath:
    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_opens_pr_and_writes_docs(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff --cached --quiet → changes staged
            _cp(0),  # commit
            _cp(0),  # push
            _cp(0, stdout="https://github.com/o/r/pull/9\n"),  # gh pr create
        ]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, SuccessResult)
        assert result.value["opened_pr"] is True
        assert result.value["pr_url"] == "https://github.com/o/r/pull/9"
        assert result.value["branch"] == ll.DEFAULT_LEARN_BRANCH
        assert result.value["rules_authored"] == 1
        # The rule doc was materialized under base_dir.
        written = tmp_path / "references/review-checks/generated/block-chaining.md"
        assert written.read_text(encoding="utf-8").startswith("# Block chaining")

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_commit_env_merges_os_environ(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff → changes staged
            _cp(0),  # commit
            _cp(0),  # push
            _cp(0, stdout="https://github.com/o/r/pull/9"),  # gh pr create
        ]

        await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        commit_call = next(
            call
            for call in mock_run.await_args_list
            if call.kwargs["args"][:2] == ["git", "commit"]
        )
        env = commit_call.kwargs["env"]
        # The bot identity is set …
        assert env["GIT_AUTHOR_NAME"] == ll._BOT_NAME
        assert env["GIT_COMMITTER_EMAIL"] == ll._BOT_EMAIL
        # … without clobbering the inherited environment (PATH/HOME).
        assert "PATH" in env

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_base_branch_passed_to_pr_create(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff
            _cp(0),  # commit
            _cp(0),  # push
            _cp(0, stdout="https://github.com/o/r/pull/9"),  # gh pr create
        ]

        result = await ll.run_learning_loop(
            base_dir=str(tmp_path), repo="o/r", base_branch="develop"
        )

        assert isinstance(result, SuccessResult)
        create_args = mock_run.await_args_list[-1].kwargs["args"]
        assert "--base" in create_args
        assert "develop" in create_args

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_recovers_existing_pr_url_on_create_failure(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff
            _cp(0),  # commit
            _cp(0),  # push
            _cp(1, stderr="a pull request already exists"),  # gh pr create fails
            _cp(0, stdout="https://github.com/o/r/pull/4"),  # gh pr view → existing url
        ]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, SuccessResult)
        assert result.value["opened_pr"] is True
        assert result.value["pr_url"] == "https://github.com/o/r/pull/4"

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_push_failure_propagates(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff
            _cp(0),  # commit
            _cp(1, stderr="remote rejected"),  # push fails
        ]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, ErrorResult)
        assert "remote rejected" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_create_failure_without_existing_pr_errors(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff
            _cp(0),  # commit
            _cp(0),  # push
            _cp(1, stderr="validation failed"),  # gh pr create fails
            _cp(1, stderr="no pr found"),  # gh pr view finds nothing
        ]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, ErrorResult)
        assert "validation failed" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_branch_creation_failure_propagates(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [_cp(1, stderr="cannot create branch")]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, ErrorResult)
        assert "cannot create branch" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_git_add_failure_propagates(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [_cp(0), _cp(1, stderr="add failed")]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, ErrorResult)
        assert "add failed" in result.error

    @pytest.mark.asyncio
    @patch("dev10x.github.learn_loop.async_run", new_callable=AsyncMock)
    @patch("dev10x.github.rule_authoring.author_reference_rules", new_callable=AsyncMock)
    async def test_commit_failure_propagates(
        self,
        mock_author: AsyncMock,
        mock_run: AsyncMock,
        tmp_path: Path,
    ) -> None:
        mock_author.return_value = ok(_authored())
        mock_run.side_effect = [
            _cp(0),  # checkout -B
            _cp(0),  # add
            _cp(1),  # diff → changes staged
            _cp(1, stderr="commit failed"),  # commit fails
        ]

        result = await ll.run_learning_loop(base_dir=str(tmp_path), repo="o/r")

        assert isinstance(result, ErrorResult)
        assert "commit failed" in result.error
