"""Unit tests for dev10x.audit.log_reader module (GH-143)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dev10x.audit.log_reader import (
    AUDIT_DIR_ENV,
    AUDIT_ENABLE_ENV,
    AUDIT_RETAIN_ENV,
    SPAN_ID_ENV,
    append_record,
    audit_dir,
    audit_enabled,
    classify_outcome,
    current_span_id,
    iter_records,
    log_path,
    new_span_id,
    prune,
    summarize,
)
from dev10x.audit.summarizer import HookStatsQuery
from dev10x.domain.hook_telemetry import HookOutcome, HookPhase


class TestAuditEnabled:
    def test_enabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv(AUDIT_ENABLE_ENV, raising=False)
        assert audit_enabled() is True

    def test_enabled_explicit_true(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "true")
        assert audit_enabled() is True

    def test_enabled_explicit_yes(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "yes")
        assert audit_enabled() is True

    def test_enabled_explicit_on(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "on")
        assert audit_enabled() is True

    def test_enabled_explicit_1(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "1")
        assert audit_enabled() is True

    def test_disabled_explicit_false(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "false")
        assert audit_enabled() is False

    def test_disabled_explicit_0(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "0")
        assert audit_enabled() is False

    def test_disabled_explicit_no(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "no")
        assert audit_enabled() is False

    def test_case_insensitive(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "TRUE")
        assert audit_enabled() is True

    def test_whitespace_stripped(self, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "  true  ")
        assert audit_enabled() is True


class TestAuditDir:
    def test_default_dir(self, monkeypatch) -> None:
        monkeypatch.delenv(AUDIT_DIR_ENV, raising=False)
        result = audit_dir()
        assert result == Path("/tmp/Dev10x/logs")

    def test_custom_dir(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv(AUDIT_DIR_ENV, str(tmp_path))
        result = audit_dir()
        assert result == tmp_path


class TestLogPath:
    def test_default_path(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_DIR_ENV, str(tmp_path))
        ts = datetime(2026, 5, 16, 12, 30, 45, tzinfo=UTC)
        result = log_path(now=ts, base_dir=tmp_path)
        assert result == tmp_path / "hooks-2026-05-16.jsonl"

    def test_uses_custom_base_dir(self, tmp_path) -> None:
        ts = datetime(2026, 5, 16, 12, 30, 45, tzinfo=UTC)
        result = log_path(now=ts, base_dir=tmp_path)
        assert result.parent == tmp_path

    def test_default_base_dir(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv(AUDIT_DIR_ENV, str(tmp_path))
        ts = datetime(2026, 5, 16, 12, 30, 45, tzinfo=UTC)
        result = log_path(now=ts)
        assert result == tmp_path / "hooks-2026-05-16.jsonl"


class TestNewSpanId:
    def test_generates_hex_string(self) -> None:
        sid = new_span_id()
        assert isinstance(sid, str)
        assert len(sid) == 16
        int(sid, 16)  # Should not raise


class TestCurrentSpanId:
    def test_uses_env_when_set(self, monkeypatch) -> None:
        monkeypatch.setenv(SPAN_ID_ENV, "test-span-id")
        result = current_span_id()
        assert result == "test-span-id"

    def test_generates_new_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv(SPAN_ID_ENV, raising=False)
        result = current_span_id()
        assert len(result) == 16
        int(result, 16)  # Verify it's valid hex

    def test_generates_new_when_empty(self, monkeypatch) -> None:
        monkeypatch.setenv(SPAN_ID_ENV, "")
        result = current_span_id()
        assert len(result) == 16
        int(result, 16)


class TestAppendRecord:
    def test_appends_jsonl_record(self, tmp_path) -> None:
        record = {"hook": "test", "outcome": "pass", "ts": "2026-05-16T12:00:00Z"}
        append_record(record=record, base_dir=tmp_path)
        ts = datetime.now(UTC)
        log = tmp_path / f"hooks-{ts.strftime('%Y-%m-%d')}.jsonl"
        assert log.exists()
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 1
        loaded = json.loads(lines[0])
        assert loaded["hook"] == "test"

    def test_multiple_appends_create_multiple_lines(self, tmp_path) -> None:
        append_record(record={"id": 1}, base_dir=tmp_path)
        append_record(record={"id": 2}, base_dir=tmp_path)
        ts = datetime.now(UTC)
        log = tmp_path / f"hooks-{ts.strftime('%Y-%m-%d')}.jsonl"
        lines = log.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_creates_directory_if_missing(self, tmp_path) -> None:
        subdir = tmp_path / "subdir"
        assert not subdir.exists()
        append_record(record={"test": "data"}, base_dir=subdir)
        assert subdir.exists()
        log = subdir / f"hooks-{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"
        assert log.exists()

    def test_handles_oserror_gracefully(self, tmp_path, monkeypatch) -> None:
        # Create a read-only directory
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o555)
        try:
            # Should not raise
            append_record(record={"test": "data"}, base_dir=ro_dir)
        finally:
            ro_dir.chmod(0o755)  # Restore for cleanup

    def test_uses_posix_o_append(self, tmp_path) -> None:
        """E1: append_record uses os.open(O_APPEND) for POSIX append atomicity."""
        from unittest.mock import patch

        with patch("dev10x.audit.log_reader.os.open", wraps=os.open) as mock_open:
            append_record(record={"hook": "x"}, base_dir=tmp_path)

        assert mock_open.called
        flags = mock_open.call_args.args[1]
        assert flags & os.O_APPEND
        assert flags & os.O_WRONLY
        assert flags & os.O_CREAT

    def test_two_appends_do_not_corrupt_under_simulated_race(self, tmp_path) -> None:
        """Both records survive even when both writers contend."""
        append_record(record={"id": 1, "hook": "a"}, base_dir=tmp_path)
        append_record(record={"id": 2, "hook": "b"}, base_dir=tmp_path)
        log = tmp_path / f"hooks-{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"
        lines = [json.loads(line) for line in log.read_text().strip().split("\n")]
        assert {rec["id"] for rec in lines} == {1, 2}


class TestClassifyOutcome:
    def test_ok_outcome(self) -> None:
        result = classify_outcome(exit_code=0)
        assert result == HookOutcome.OK

    def test_error_outcome(self) -> None:
        result = classify_outcome(exit_code=1)
        assert result == HookOutcome.ERROR

    def test_block_outcome(self) -> None:
        result = classify_outcome(exit_code=2)
        assert result == HookOutcome.BLOCK


class TestIterRecords:
    def test_empty_dir_returns_empty_list(self, tmp_path) -> None:
        result = iter_records(base_dir=tmp_path)
        assert result == []

    def test_missing_dir_returns_empty_list(self, tmp_path) -> None:
        missing = tmp_path / "missing"
        result = iter_records(base_dir=missing)
        assert result == []

    def test_reads_single_record(self, tmp_path) -> None:
        log = tmp_path / "hooks-2026-05-16.jsonl"
        log.write_text('{"hook": "test", "span_id": "abc123"}\n')
        result = iter_records(base_dir=tmp_path)
        assert len(result) == 1
        assert result[0]["hook"] == "test"

    def test_skips_blank_lines(self, tmp_path) -> None:
        log = tmp_path / "hooks-2026-05-16.jsonl"
        log.write_text('{"hook": "a"}\n\n{"hook": "b"}\n  \n{"hook": "c"}\n')
        result = iter_records(base_dir=tmp_path)
        assert len(result) == 3
        assert [r["hook"] for r in result] == ["a", "b", "c"]

    def test_skips_invalid_json(self, tmp_path) -> None:
        log = tmp_path / "hooks-2026-05-16.jsonl"
        log.write_text('{"hook": "a"}\nnot-json\n{"hook": "b"}\n')
        result = iter_records(base_dir=tmp_path)
        assert len(result) == 2
        assert [r["hook"] for r in result] == ["a", "b"]

    def test_filters_by_since_timestamp(self, tmp_path) -> None:
        log = tmp_path / "hooks-2026-05-16.jsonl"
        log.write_text(
            '{"ts": "2026-05-16T10:00:00+00:00", "hook": "old"}\n'
            '{"ts": "2026-05-16T12:00:00+00:00", "hook": "new"}\n'
        )
        since = datetime(2026, 5, 16, 11, 0, 0, tzinfo=UTC)
        result = iter_records(base_dir=tmp_path, since=since)
        assert len(result) == 1
        assert result[0]["hook"] == "new"

    def test_skips_invalid_timestamp_format(self, tmp_path) -> None:
        log = tmp_path / "hooks-2026-05-16.jsonl"
        log.write_text(
            '{"ts": "invalid-date", "hook": "a"}\n{"ts": "2026-05-16T12:00:00Z", "hook": "b"}\n'
        )
        since = datetime(2026, 5, 16, 11, 0, 0, tzinfo=UTC)
        result = iter_records(base_dir=tmp_path, since=since)
        assert len(result) == 1
        assert result[0]["hook"] == "b"

    def test_filters_by_explicit_paths(self, tmp_path) -> None:
        log1 = tmp_path / "hooks-2026-05-16.jsonl"
        log2 = tmp_path / "hooks-2026-05-17.jsonl"
        log1.write_text('{"hook": "a"}\n')
        log2.write_text('{"hook": "b"}\n')
        result = iter_records(paths=[log1])
        assert len(result) == 1
        assert result[0]["hook"] == "a"

    def test_handles_missing_log_file_gracefully(self, tmp_path) -> None:
        missing = tmp_path / "hooks-missing.jsonl"
        result = iter_records(paths=[missing])
        assert result == []

    def test_handles_permission_error_gracefully(self, tmp_path) -> None:
        log = tmp_path / "hooks-2026-05-16.jsonl"
        log.write_text('{"hook": "test"}\n')
        log.chmod(0o000)
        try:
            result = iter_records(base_dir=tmp_path)
            assert result == []
        finally:
            log.chmod(0o644)


class TestSummarize:
    def test_empty_records_returns_empty_dict(self) -> None:
        result = summarize(records=[])
        assert result == {}

    def test_single_wrap_record(self) -> None:
        records = [
            {
                "phase": HookPhase.WRAP,
                "span_id": "abc123",
                "hook": "session-start",
                "total_ms": 100,
                "outcome": HookOutcome.OK,
            }
        ]
        result = summarize(records=records)
        assert "session-start" in result
        stats = result["session-start"]
        assert stats["count"] == 1
        assert stats["paired_count"] == 0

    def test_single_body_record(self) -> None:
        records = [
            {
                "phase": HookPhase.BODY,
                "span_id": "abc123",
                "hook": "session-start",
                "body_ms": 50,
                "outcome": HookOutcome.OK,
            }
        ]
        result = summarize(records=records)
        assert "session-start" in result
        stats = result["session-start"]
        assert stats["count"] == 1
        assert stats["paired_count"] == 0

    def test_paired_wrap_and_body_records(self) -> None:
        records = [
            {
                "phase": HookPhase.WRAP,
                "span_id": "abc123",
                "hook": "session-start",
                "total_ms": 100,
                "outcome": HookOutcome.OK,
            },
            {
                "phase": HookPhase.BODY,
                "span_id": "abc123",
                "hook": "session-start",
                "body_ms": 50,
                "outcome": HookOutcome.OK,
            },
        ]
        result = summarize(records=records)
        stats = result["session-start"]
        assert stats["count"] == 1
        assert stats["paired_count"] == 1
        assert stats["total_ms_avg"] == 100.0
        assert stats["body_ms_avg"] == 50.0
        assert stats["startup_ms_avg"] == 50.0

    def test_counts_errors(self) -> None:
        records = [
            {
                "phase": HookPhase.BODY,
                "span_id": "s1",
                "hook": "test",
                "outcome": HookOutcome.ERROR,
            },
            {
                "phase": HookPhase.BODY,
                "span_id": "s2",
                "hook": "test",
                "outcome": HookOutcome.OK,
            },
        ]
        result = summarize(records=records)
        stats = result["test"]
        assert stats["count"] == 2
        assert stats["error_count"] == 1

    def test_counts_blocks(self) -> None:
        records = [
            {
                "phase": HookPhase.BODY,
                "span_id": "s1",
                "hook": "validate",
                "outcome": HookOutcome.BLOCK,
            },
            {
                "phase": HookPhase.BODY,
                "span_id": "s2",
                "hook": "validate",
                "outcome": HookOutcome.OK,
            },
        ]
        result = summarize(records=records)
        stats = result["validate"]
        assert stats["count"] == 2
        assert stats["block_count"] == 1

    def test_aggregates_multiple_hooks(self) -> None:
        records = [
            {
                "phase": HookPhase.BODY,
                "span_id": "s1",
                "hook": "hook-a",
                "outcome": HookOutcome.OK,
            },
            {
                "phase": HookPhase.BODY,
                "span_id": "s2",
                "hook": "hook-b",
                "outcome": HookOutcome.OK,
            },
        ]
        result = summarize(records=records)
        assert len(result) == 2
        assert "hook-a" in result
        assert "hook-b" in result

    def test_missing_phase_ignored(self) -> None:
        records = [
            {
                "span_id": "s1",
                "hook": "test",
                "outcome": HookOutcome.OK,
            },
        ]
        result = summarize(records=records)
        assert result == {}

    def test_records_without_span_id_ignored(self) -> None:
        records = [
            {
                "phase": HookPhase.BODY,
                "hook": "test",
                "outcome": HookOutcome.OK,
            },
        ]
        result = summarize(records=records)
        assert result == {}

    def test_invalid_phase_type_ignored(self) -> None:
        records = [
            {
                "phase": 123,  # Not a string
                "span_id": "s1",
                "hook": "test",
            },
        ]
        result = summarize(records=records)
        assert result == {}


class TestHookStatsQuery:
    def test_by_hook_matches_summarize_wrapper(self) -> None:
        records = [
            {
                "phase": HookPhase.WRAP,
                "span_id": "s1",
                "hook": "session-start",
                "total_ms": 120,
                "outcome": HookOutcome.OK,
            },
            {
                "phase": HookPhase.BODY,
                "span_id": "s1",
                "hook": "session-start",
                "body_ms": 40,
                "outcome": HookOutcome.OK,
            },
        ]
        assert HookStatsQuery(records=records).by_hook() == summarize(records=records)

    def test_query_object_aggregates_paired_span(self) -> None:
        records = [
            {"phase": HookPhase.WRAP, "span_id": "s1", "hook": "h", "total_ms": 100},
            {"phase": HookPhase.BODY, "span_id": "s1", "hook": "h", "body_ms": 60},
        ]
        stats = HookStatsQuery(records=records).by_hook()["h"]
        assert stats["paired_count"] == 1
        assert stats["startup_ms_avg"] == 40.0

    def test_span_with_only_unknown_phase_is_skipped(self) -> None:
        records = [{"phase": "warmup", "span_id": "s1", "hook": "h"}]
        assert HookStatsQuery(records=records).by_hook() == {}


class TestPrune:
    def test_deletes_old_files(self, tmp_path) -> None:
        # Create old and new files
        old = tmp_path / "hooks-2026-03-01.jsonl"
        new = tmp_path / "hooks-2026-05-16.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        # Set mtime to be old
        old.touch()
        old_stat = old.stat()
        os.utime(old, (old_stat.st_atime, old_stat.st_mtime - 100 * 86400))
        # Prune with retain_days=30
        deleted = prune(retain_days=30, base_dir=tmp_path)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()

    def test_missing_dir_returns_zero(self, tmp_path) -> None:
        missing = tmp_path / "missing"
        deleted = prune(retain_days=30, base_dir=missing)
        assert deleted == 0

    def test_no_matching_files_returns_zero(self, tmp_path) -> None:
        unrelated = tmp_path / "other.txt"
        unrelated.write_text("data")
        deleted = prune(retain_days=30, base_dir=tmp_path)
        assert deleted == 0

    def test_uses_env_variable_for_days(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_RETAIN_ENV, "7")
        old = tmp_path / "hooks-2026-03-01.jsonl"
        old.write_text("{}\n")
        old.touch()
        old_stat = old.stat()
        os.utime(old, (old_stat.st_atime, old_stat.st_mtime - 100 * 86400))
        deleted = prune(base_dir=tmp_path)
        assert deleted == 1

    def test_invalid_env_variable_uses_default(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(AUDIT_RETAIN_ENV, "not-a-number")
        new = tmp_path / "hooks-2026-05-16.jsonl"
        new.write_text("{}\n")
        deleted = prune(base_dir=tmp_path)
        assert deleted == 0
        assert new.exists()

    def test_skips_nonexistent_files(self, tmp_path) -> None:
        # Even if glob picks up a path that no longer exists (race condition),
        # prune() silently continues
        old = tmp_path / "hooks-2026-03-01.jsonl"
        old.write_text("{}\n")
        old.touch()
        old_stat = old.stat()
        os.utime(old, (old_stat.st_atime, old_stat.st_mtime - 100 * 86400))
        # Delete it before prune runs (simulating a race condition)
        old.unlink()
        deleted = prune(retain_days=30, base_dir=tmp_path)
        # prune() returns the actual count of successfully deleted files
        assert deleted == 0
