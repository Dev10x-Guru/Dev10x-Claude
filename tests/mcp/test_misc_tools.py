"""Tests for misc_tools MCP adapter (GH-580).

Covers argument forwarding (especially cwd), ok/err → dict translation,
and error paths for each adapter function in src/dev10x/mcp/misc_tools.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dev10x.domain.common.result import err, ok
from dev10x.mcp import server_cli as cli_server


class TestMktmp:
    @pytest.mark.asyncio
    @patch("dev10x.utilities.mktmp", new_callable=AsyncMock)
    async def test_delegates_to_utilities_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"path": "/tmp/Dev10x/git/msg-abc.txt"})

        result = await cli_server.mktmp(namespace="git", prefix="msg", ext=".txt")

        assert result == {"path": "/tmp/Dev10x/git/msg-abc.txt"}
        assert mock_fn.call_args.kwargs["namespace"] == "git"
        assert mock_fn.call_args.kwargs["prefix"] == "msg"
        assert mock_fn.call_args.kwargs["ext"] == ".txt"

    @pytest.mark.asyncio
    @patch("dev10x.utilities.mktmp", new_callable=AsyncMock)
    async def test_forwards_directory_and_create_flags(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"path": "/tmp/Dev10x/fanout/wave-01/"})

        await cli_server.mktmp(
            namespace="fanout",
            prefix="wave",
            directory=True,
            create=True,
        )

        assert mock_fn.call_args.kwargs["directory"] is True
        assert mock_fn.call_args.kwargs["create"] is True

    @pytest.mark.asyncio
    @patch("dev10x.utilities.mktmp", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("cannot create temp dir")

        result = await cli_server.mktmp(namespace="x", prefix="y")

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.utilities.mktmp", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok({"path": "/tmp/Dev10x/git/msg.txt"})

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.mktmp(
                namespace="git",
                prefix="msg",
                cwd=str(tmp_path),
            )

        mock_use_cwd.assert_called_once_with(str(tmp_path))


class TestSlackThreadIsForward:
    @pytest.mark.asyncio
    @patch("dev10x.utilities.slack.slack_thread_is_forward", new_callable=AsyncMock)
    async def test_delegates_to_slack_helper(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok(
            {
                "is_forward": True,
                "confidence": "high",
                "signals": ["short_body", "external_link"],
                "upstream_hints": [],
            }
        )

        result = await cli_server.slack_thread_is_forward(
            parent_body="FYI see https://example.com",
            reply_count=0,
        )

        assert result["is_forward"] is True
        assert result["confidence"] == "high"
        assert mock_fn.call_args.kwargs == {
            "parent_body": "FYI see https://example.com",
            "reply_count": 0,
        }

    @pytest.mark.asyncio
    @patch("dev10x.utilities.slack.slack_thread_is_forward", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("analysis failed")

        result = await cli_server.slack_thread_is_forward(
            parent_body="hello world",
            reply_count=5,
        )

        assert "error" in result


class TestUpdatePaths:
    @pytest.mark.asyncio
    @patch("dev10x.permission.update_paths", new_callable=AsyncMock)
    async def test_delegates_to_permission_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": "3 paths updated"})

        result = await cli_server.update_paths()

        assert result == {"success": True, "output": "3 paths updated"}
        mock_fn.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("dev10x.permission.update_paths", new_callable=AsyncMock)
    async def test_forwards_all_flags(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": ""})

        await cli_server.update_paths(
            version="1.2.3",
            dry_run=True,
            ensure_base=True,
            generalize=True,
            ensure_scripts=True,
            ensure_reads=True,
            init=True,
            quiet=True,
        )

        kw = mock_fn.call_args.kwargs
        assert kw["version"] == "1.2.3"
        assert kw["dry_run"] is True
        assert kw["ensure_base"] is True
        assert kw["generalize"] is True
        assert kw["ensure_scripts"] is True
        assert kw["ensure_reads"] is True
        assert kw["init"] is True
        assert kw["quiet"] is True

    @pytest.mark.asyncio
    @patch("dev10x.permission.update_paths", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("settings.json not found")

        result = await cli_server.update_paths()

        assert "error" in result


class TestGenerateSkillIndex:
    @pytest.mark.asyncio
    @patch("dev10x.skill_index.generate_all", new_callable=AsyncMock)
    async def test_delegates_to_skill_index_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": "SKILLS.md updated"})

        result = await cli_server.generate_skill_index()

        assert result == {"success": True, "output": "SKILLS.md updated"}
        assert mock_fn.call_args.kwargs["force"] is False

    @pytest.mark.asyncio
    @patch("dev10x.skill_index.generate_all", new_callable=AsyncMock)
    async def test_forwards_force_flag(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok({"success": True, "output": ""})

        await cli_server.generate_skill_index(force=True)

        assert mock_fn.call_args.kwargs["force"] is True

    @pytest.mark.asyncio
    @patch("dev10x.skill_index.generate_all", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("skills directory not found")

        result = await cli_server.generate_skill_index()

        assert "error" in result


class TestRecordUpgrade:
    @patch("dev10x.domain.install_version.record_upgrade")
    def test_delegates_to_install_version_module(self, mock_fn: MagicMock) -> None:
        mock_fn.return_value = ok({"version": "1.2.3", "path": "/home/user/.config/dev10x"})

        import asyncio

        result = asyncio.run(cli_server.record_upgrade(version="1.2.3"))

        assert result == {"version": "1.2.3", "path": "/home/user/.config/dev10x"}
        assert mock_fn.call_args.kwargs["version"] == "1.2.3"

    @patch("dev10x.domain.install_version.record_upgrade")
    def test_forwards_none_version(self, mock_fn: MagicMock) -> None:
        mock_fn.return_value = ok({"version": "0.99.0", "path": "/home/user/.config/dev10x"})

        import asyncio

        asyncio.run(cli_server.record_upgrade())

        assert mock_fn.call_args.kwargs["version"] is None

    @patch("dev10x.domain.install_version.record_upgrade")
    def test_returns_error_on_failure(self, mock_fn: MagicMock) -> None:
        mock_fn.return_value = err("plugin.json not found")

        import asyncio

        result = asyncio.run(cli_server.record_upgrade())

        assert "error" in result


class TestRunTests:
    @pytest.mark.asyncio
    @patch("dev10x.runner.run_tests", new_callable=AsyncMock)
    async def test_delegates_to_runner_module(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok(
            {
                "returncode": 0,
                "summary": "42 passed",
                "passed": 42,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "coverage_percent": 87,
                "failed_tests": [],
                "missing_coverage": [],
                "stdout": "",
                "stderr": "",
            }
        )

        result = await cli_server.run_tests()

        assert result["returncode"] == 0
        assert result["passed"] == 42
        assert mock_fn.call_args.kwargs["args"] is None
        assert mock_fn.call_args.kwargs["coverage"] is True

    @pytest.mark.asyncio
    @patch("dev10x.runner.run_tests", new_callable=AsyncMock)
    async def test_forwards_args_and_flags(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = ok(
            {
                "returncode": 0,
                "summary": "5 passed",
                "passed": 5,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "coverage_percent": None,
                "failed_tests": [],
                "missing_coverage": [],
                "stdout": "",
                "stderr": "",
            }
        )

        await cli_server.run_tests(
            args=["tests/mcp/"],
            coverage=False,
            timeout=120,
        )

        assert mock_fn.call_args.kwargs["args"] == ["tests/mcp/"]
        assert mock_fn.call_args.kwargs["coverage"] is False
        assert mock_fn.call_args.kwargs["timeout"] == 120

    @pytest.mark.asyncio
    @patch("dev10x.runner.run_tests", new_callable=AsyncMock)
    async def test_returns_error_on_failure(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = err("pytest not found")

        result = await cli_server.run_tests()

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.runner.run_tests", new_callable=AsyncMock)
    async def test_forwards_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = ok(
            {
                "returncode": 0,
                "summary": "",
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "coverage_percent": None,
                "failed_tests": [],
                "missing_coverage": [],
                "stdout": "",
                "stderr": "",
            }
        )

        with patch("dev10x.subprocess_utils.use_cwd") as mock_use_cwd:
            await cli_server.run_tests(cwd=str(tmp_path))

        mock_use_cwd.assert_called_once_with(str(tmp_path))
