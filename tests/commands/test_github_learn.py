"""Tests for `dev10x github learn` (GH-353).

Contract class: mock
  The command path patches the learn-loop orchestrator so no git/gh
  subprocess runs; only the CLI seam (option wiring, stdout, exit code)
  is exercised here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from dev10x.cli import cli
from dev10x.domain.common.result import err, ok


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestLearnCommandRegistration:
    def test_learn_exposed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["github", "--help"])

        assert result.exit_code == 0
        assert "learn" in result.output

    def test_learn_help_lists_options(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["github", "learn", "--help"])

        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--base-dir" in result.output
        assert "--base" in result.output


class TestLearnCommand:
    @patch("dev10x.github.learn_loop.run_learning_loop", new_callable=AsyncMock)
    def test_opened_pr_prints_url(self, mock_loop: AsyncMock, runner: CliRunner) -> None:
        mock_loop.return_value = ok(
            {
                "opened_pr": True,
                "pr_url": "https://github.com/o/r/pull/9",
                "branch": "dev10x/learned-rules",
                "rules_authored": 2,
                "summary": {},
            }
        )

        result = runner.invoke(
            cli, ["github", "learn", "--repo", "o/r", "--base-dir", "/tmp/work"]
        )

        assert result.exit_code == 0, result.output
        assert "https://github.com/o/r/pull/9" in result.output
        assert "2 rule(s)" in result.output
        assert mock_loop.await_args.kwargs["repo"] == "o/r"
        assert mock_loop.await_args.kwargs["base_dir"] == "/tmp/work"

    @patch("dev10x.github.learn_loop.run_learning_loop", new_callable=AsyncMock)
    def test_no_pr_prints_reason(self, mock_loop: AsyncMock, runner: CliRunner) -> None:
        mock_loop.return_value = ok(
            {
                "opened_pr": False,
                "reason": "no validated review patterns",
                "rules_authored": 0,
                "summary": {},
            }
        )

        result = runner.invoke(cli, ["github", "learn", "--repo", "o/r"])

        assert result.exit_code == 0, result.output
        assert "no validated review patterns" in result.output

    @patch("dev10x.github.learn_loop.run_learning_loop", new_callable=AsyncMock)
    def test_default_base_dir_is_cwd(self, mock_loop: AsyncMock, runner: CliRunner) -> None:
        import os

        mock_loop.return_value = ok(
            {"opened_pr": False, "reason": "x", "rules_authored": 0, "summary": {}}
        )

        result = runner.invoke(cli, ["github", "learn"])

        assert result.exit_code == 0, result.output
        assert mock_loop.await_args.kwargs["base_dir"] == os.getcwd()
        assert mock_loop.await_args.kwargs["repo"] is None

    @patch("dev10x.github.learn_loop.run_learning_loop", new_callable=AsyncMock)
    def test_error_exits_nonzero(self, mock_loop: AsyncMock, runner: CliRunner) -> None:
        mock_loop.return_value = err("git push failed")

        result = runner.invoke(cli, ["github", "learn", "--repo", "o/r"])

        assert result.exit_code == 1
        assert "git push failed" in result.output
