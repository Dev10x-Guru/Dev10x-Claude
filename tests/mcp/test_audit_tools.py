"""Wire-contract tests for the audit_tools MCP adapter (GH-556).

Verifies that each of the five MCP tools:

- Routes domain errors through ``to_wire`` and returns ``{"error": ...}``
  (branch on presence of "error" key — never on empty dict).
- Passes keyword arguments to the domain function unchanged.
- Returns a success dict (no "error" key) on the happy path.

The domain layer already has its own unit tests (tests/audit/test_audit.py),
so these tests mock at the ``dev10x.audit.*`` boundary and focus on the
adapter contract, not on domain logic.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dev10x.mcp import server_cli as cli_server

# ── audit_extract_session ────────────────────────────────────────────────────


class TestAuditExtractSessionErrorContract:
    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_missing_jsonl_file_returns_error_key(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """Script non-zero exit → wire dict contains 'error'."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="No such file or directory: /tmp/missing.jsonl",
        )

        result = await cli_server.audit_extract_session(
            jsonl_path="/tmp/missing.jsonl",
        )

        assert "error" in result
        assert "No such file" in result["error"]

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_malformed_jsonl_script_failure_returns_error_key(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """Malformed JSONL triggers script failure → error on wire."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="JSONDecodeError: line 3",
        )

        result = await cli_server.audit_extract_session(
            jsonl_path="/tmp/bad.jsonl",
        )

        assert "error" in result
        assert "JSONDecodeError" in result["error"]

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_success_has_no_error_key(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Extracted 10 turns",
            stderr="",
        )

        result = await cli_server.audit_extract_session(
            jsonl_path="/tmp/session.jsonl",
        )

        assert "error" not in result
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_output_path_forwarded(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """output_path arg is passed through to the domain function."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="OK",
            stderr="",
        )

        await cli_server.audit_extract_session(
            jsonl_path="/tmp/session.jsonl",
            output_path="/tmp/out.md",
        )

        call_args = mock_run.call_args
        assert "/tmp/out.md" in call_args.args[1:]


# ── audit_analyze_actions ────────────────────────────────────────────────────


class TestAuditAnalyzeActionsErrorContract:
    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_missing_transcript_returns_error_key(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="transcript not found",
        )

        result = await cli_server.audit_analyze_actions(
            transcript_path="/tmp/missing.md",
        )

        assert "error" in result
        assert "transcript not found" in result["error"]

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_empty_transcript_script_failure_returns_error_key(
        self,
        mock_run: AsyncMock,
    ) -> None:
        """Empty / unparseable transcript → script exits non-zero."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="No actions found",
        )

        result = await cli_server.audit_analyze_actions(
            transcript_path="/tmp/empty.md",
        )

        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_success_has_no_error_key(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Found 5 actions",
            stderr="",
        )

        result = await cli_server.audit_analyze_actions(
            transcript_path="/tmp/transcript.md",
        )

        assert "error" not in result
        assert result["success"] is True


# ── audit_analyze_permissions ────────────────────────────────────────────────


class TestAuditAnalyzePermissionsErrorContract:
    @pytest.mark.asyncio
    async def test_missing_transcript_returns_error_key(
        self,
        tmp_path: Path,
    ) -> None:
        """Non-existent transcript → domain returns err() → wire has 'error'."""
        result = await cli_server.audit_analyze_permissions(
            transcript_path=str(tmp_path / "missing.md"),
        )

        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_build_audit_report_exception_returns_error_key(
        self,
        tmp_path: Path,
    ) -> None:
        """build_audit_report raising → err() → wire has 'error'."""
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# session\n")

        with patch(
            "dev10x.audit.analyze.build_audit_report",
            side_effect=RuntimeError("internal failure"),
        ):
            result = await cli_server.audit_analyze_permissions(
                transcript_path=str(transcript),
            )

        assert "error" in result
        assert "internal failure" in result["error"]

    @pytest.mark.asyncio
    async def test_success_has_no_error_key(
        self,
        tmp_path: Path,
    ) -> None:
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# empty session\n")
        settings = tmp_path / "settings.json"
        settings.write_text('{"permissions": {"allow": []}}')

        result = await cli_server.audit_analyze_permissions(
            transcript_path=str(transcript),
            settings_path=str(settings),
        )

        assert "error" not in result
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_settings_path_forwarded(
        self,
        tmp_path: Path,
    ) -> None:
        """Custom settings_path is passed to the in-process analysis."""
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# session\n")
        settings = tmp_path / "custom_settings.json"
        settings.write_text('{"permissions": {"allow": ["Bash(echo *)"]}}')

        with patch("dev10x.audit.analyze.build_audit_report") as mock_build:
            mock_build.return_value = MagicMock(render_markdown=lambda: "# Report\n")
            await cli_server.audit_analyze_permissions(
                transcript_path=str(transcript),
                settings_path=str(settings),
            )

        called_settings = mock_build.call_args.kwargs["settings_path"]
        assert called_settings == settings


# ── audit_hook_log_path ──────────────────────────────────────────────────────


class TestAuditHookLogPathContract:
    @pytest.mark.asyncio
    async def test_success_has_no_error_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """hook_log_path always succeeds — result must never carry 'error'."""
        monkeypatch.delenv("DEV10X_HOOK_AUDIT_DIR", raising=False)
        monkeypatch.delenv("DEV10X_HOOK_AUDIT", raising=False)

        result = await cli_server.audit_hook_log_path()

        assert "error" not in result
        # Mandatory wire-contract keys
        assert "audit_dir" in result
        assert "today_log" in result
        assert "today_log_exists" in result
        assert "audit_dir_exists" in result
        assert "available_logs" in result
        assert "audit_disabled" in result

    @pytest.mark.asyncio
    async def test_nonexistent_audit_dir_returns_exists_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Audit dir that does not exist → today_log_exists=False, no error."""
        nonexistent = tmp_path / "no-such-dir"
        monkeypatch.setenv("DEV10X_HOOK_AUDIT_DIR", str(nonexistent))

        result = await cli_server.audit_hook_log_path()

        assert "error" not in result
        assert result["audit_dir_exists"] is False
        assert result["today_log_exists"] is False
        assert result["available_logs"] == []

    @pytest.mark.asyncio
    async def test_audit_disabled_env_reflected_in_wire(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DEV10X_HOOK_AUDIT_DIR", str(tmp_path))
        monkeypatch.setenv("DEV10X_HOOK_AUDIT", "0")

        result = await cli_server.audit_hook_log_path()

        assert "error" not in result
        assert result["audit_disabled"] is True


# ── audit_hook_recent ────────────────────────────────────────────────────────


class TestAuditHookRecentErrorContract:
    @pytest.mark.asyncio
    async def test_missing_log_file_returns_error_key(
        self,
        tmp_path: Path,
    ) -> None:
        """Explicit log_path that does not exist → wire has 'error'."""
        missing = tmp_path / "hooks-2099-06-01.jsonl"

        result = await cli_server.audit_hook_recent(
            log_path=str(missing),
        )

        assert "error" in result
        assert result.get("exists") is False
        assert result.get("records") == []

    @pytest.mark.asyncio
    async def test_empty_log_file_returns_zero_records(
        self,
        tmp_path: Path,
    ) -> None:
        """Existing but empty log → success with count=0."""
        log = tmp_path / "hooks-2026-06-01.jsonl"
        log.write_text("")

        result = await cli_server.audit_hook_recent(
            log_path=str(log),
        )

        assert "error" not in result
        assert result["count"] == 0
        assert result["records"] == []

    @pytest.mark.asyncio
    async def test_malformed_jsonl_lines_are_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        """Malformed lines in the log are silently skipped, not an error."""
        log = tmp_path / "hooks-2026-06-01.jsonl"
        log.write_text(
            '{"hook": "ok", "span_id": "s1"}\n'
            "NOT VALID JSON\n"
            "\n"
            '{"hook": "ok2", "span_id": "s2"}\n',
        )

        result = await cli_server.audit_hook_recent(
            log_path=str(log),
        )

        assert "error" not in result
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_hook_name_filter_forwarded(
        self,
        tmp_path: Path,
    ) -> None:
        """hook_name filter is applied at the domain layer."""
        log = tmp_path / "hooks-2026-06-01.jsonl"
        log.write_text(
            '{"hook": "session-start", "span_id": "s1"}\n'
            '{"hook": "validate-bash", "span_id": "s2"}\n'
            '{"hook": "session-start", "span_id": "s3"}\n',
        )

        result = await cli_server.audit_hook_recent(
            log_path=str(log),
            hook_name="session-start",
        )

        assert "error" not in result
        assert result["count"] == 2
        assert all(r["hook"] == "session-start" for r in result["records"])

    @pytest.mark.asyncio
    async def test_limit_applied_to_tail(
        self,
        tmp_path: Path,
    ) -> None:
        """limit=1 returns only the most recent record."""
        log = tmp_path / "hooks-2026-06-01.jsonl"
        log.write_text(
            '{"hook": "a", "span_id": "s1"}\n'
            '{"hook": "b", "span_id": "s2"}\n'
            '{"hook": "c", "span_id": "s3"}\n',
        )

        result = await cli_server.audit_hook_recent(
            log_path=str(log),
            limit=1,
        )

        assert "error" not in result
        assert result["count"] == 1
        assert result["records"][0]["hook"] == "c"
