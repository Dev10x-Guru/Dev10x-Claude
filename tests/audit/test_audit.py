from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

audit_mod = pytest.importorskip("dev10x.audit", reason="dev10x not installed")


class TestExtractSession:
    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_returns_output_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Extracted 42 turns",
            stderr="",
        )
        result = await audit_mod.extract_session(jsonl_path="/tmp/session.jsonl")
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="File not found",
        )
        result = await audit_mod.extract_session(jsonl_path="/tmp/missing.jsonl")
        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_passes_output_path(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        await audit_mod.extract_session(
            jsonl_path="/tmp/session.jsonl",
            output_path="/tmp/output.md",
        )
        call_args = mock_run.call_args
        assert "/tmp/output.md" in call_args.args[1:]


class TestAnalyzeActions:
    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_returns_output_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Analyzed 15 actions",
            stderr="",
        )
        result = await audit_mod.analyze_actions(transcript_path="/tmp/transcript.md")
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("dev10x.audit.async_run_script", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Parse error",
        )
        result = await audit_mod.analyze_actions(transcript_path="/tmp/transcript.md")
        assert "error" in result


class TestAnalyzePermissions:
    """GH-142: analyze_permissions now runs in-process via the factory."""

    @pytest.mark.asyncio
    async def test_missing_transcript_returns_error(self, tmp_path) -> None:
        result = await audit_mod.analyze_permissions(
            transcript_path=str(tmp_path / "missing.md"),
        )
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_transcript_produces_report(self, tmp_path) -> None:
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# empty transcript\n")
        settings = tmp_path / "settings.json"
        settings.write_text('{"permissions": {"allow": []}}')

        result = await audit_mod.analyze_permissions(
            transcript_path=str(transcript),
            settings_path=str(settings),
        )

        assert result["success"] is True
        assert "Permission Friction Analysis" in result["output"]

    @pytest.mark.asyncio
    async def test_writes_to_output_path(self, tmp_path) -> None:
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# empty\n")
        settings = tmp_path / "settings.json"
        settings.write_text('{"permissions": {"allow": []}}')
        output = tmp_path / "report.md"

        result = await audit_mod.analyze_permissions(
            transcript_path=str(transcript),
            settings_path=str(settings),
            output_path=str(output),
        )

        assert result["success"] is True
        assert output.exists()
        assert "Permission Friction Analysis" in output.read_text()

    @pytest.mark.asyncio
    async def test_factory_failure_returns_error(self, tmp_path) -> None:
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# transcript\n")

        with patch(
            "dev10x.audit.analyze.build_audit_report",
            side_effect=RuntimeError("boom"),
        ):
            result = await audit_mod.analyze_permissions(
                transcript_path=str(transcript),
            )

        assert "error" in result
        assert "boom" in result["error"]


class TestHookLogPath:
    @pytest.mark.asyncio
    async def test_resolves_default_dir(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DEV10X_HOOK_AUDIT_DIR", raising=False)
        monkeypatch.delenv("DEV10X_HOOK_AUDIT", raising=False)
        result = await audit_mod.hook_log_path()
        assert result["audit_dir"] == "/tmp/Dev10x/hook-audit"
        assert result["audit_disabled"] is False

    @pytest.mark.asyncio
    async def test_honors_env_override(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_AUDIT_DIR", str(tmp_path))
        result = await audit_mod.hook_log_path()
        assert result["audit_dir"] == str(tmp_path)
        assert result["audit_dir_exists"] is True
        assert result["today_log_exists"] is False
        assert result["available_logs"] == []

    @pytest.mark.asyncio
    async def test_lists_available_logs(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_AUDIT_DIR", str(tmp_path))
        (tmp_path / "hooks-2026-04-28.jsonl").write_text("{}\n")
        (tmp_path / "hooks-2026-04-29.jsonl").write_text("{}\n")
        (tmp_path / "unrelated.txt").write_text("x")
        result = await audit_mod.hook_log_path()
        assert result["available_logs"] == [
            "hooks-2026-04-28.jsonl",
            "hooks-2026-04-29.jsonl",
        ]

    @pytest.mark.asyncio
    async def test_audit_disabled_flag(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_AUDIT_DIR", str(tmp_path))
        monkeypatch.setenv("DEV10X_HOOK_AUDIT", "0")
        result = await audit_mod.hook_log_path()
        assert result["audit_disabled"] is True


class TestHookRecent:
    @pytest.mark.asyncio
    async def test_missing_log_returns_error(self, tmp_path) -> None:
        target = tmp_path / "hooks-2099-01-01.jsonl"
        result = await audit_mod.hook_recent(log_path=str(target))
        assert result["exists"] is False
        assert result["records"] == []
        assert "error" in result

    @pytest.mark.asyncio
    async def test_reads_records_with_limit(self, tmp_path) -> None:
        log = tmp_path / "log.jsonl"
        log.write_text(
            '{"hook": "a", "span_id": "s1"}\n'
            "\n"
            "not-json\n"
            '{"hook": "b", "span_id": "s2"}\n'
            '{"hook": "c", "span_id": "s3"}\n'
        )
        result = await audit_mod.hook_recent(log_path=str(log), limit=2)
        assert result["count"] == 2
        assert [r["hook"] for r in result["records"]] == ["b", "c"]

    @pytest.mark.asyncio
    async def test_filters_by_hook_name(self, tmp_path) -> None:
        log = tmp_path / "log.jsonl"
        log.write_text(
            '{"hook": "session-start", "span_id": "s1"}\n'
            '{"hook": "validate-bash", "span_id": "s2"}\n'
            '{"hook": "session-start", "span_id": "s3"}\n'
        )
        result = await audit_mod.hook_recent(
            log_path=str(log),
            hook_name="session-start",
        )
        assert result["count"] == 2
        assert all(r["hook"] == "session-start" for r in result["records"])

    @pytest.mark.asyncio
    async def test_filters_by_span_id(self, tmp_path) -> None:
        log = tmp_path / "log.jsonl"
        log.write_text('{"hook": "a", "span_id": "abc"}\n{"hook": "b", "span_id": "xyz"}\n')
        result = await audit_mod.hook_recent(log_path=str(log), span_id="xyz")
        assert result["count"] == 1
        assert result["records"][0]["span_id"] == "xyz"

    @pytest.mark.asyncio
    async def test_zero_limit_returns_all(self, tmp_path) -> None:
        log = tmp_path / "log.jsonl"
        log.write_text('{"hook": "a"}\n{"hook": "b"}\n{"hook": "c"}\n')
        result = await audit_mod.hook_recent(log_path=str(log), limit=0)
        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_default_path_uses_today(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_AUDIT_DIR", str(tmp_path))
        result = await audit_mod.hook_recent()
        assert result["exists"] is False
        assert "hooks-" in result["log_path"]
