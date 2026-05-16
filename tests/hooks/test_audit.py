"""Tests for the hook audit module (GH-860)."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dev10x.audit.log_reader import (
    AUDIT_DIR_ENV,
    AUDIT_ENABLE_ENV,
    AUDIT_RETAIN_ENV,
    SPAN_ID_ENV,
    iter_records,
    prune,
    summarize,
)
from dev10x.hooks.audit_emit import (
    audit_hook,
    cli_wrap_record,
    finish_wrap_context,
    new_wrap_context,
    write_wrap_record,
)


@pytest.fixture()
def audit_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_dir = tmp_path / "logs"
    monkeypatch.setenv(AUDIT_DIR_ENV, str(log_dir))
    monkeypatch.delenv(AUDIT_ENABLE_ENV, raising=False)
    monkeypatch.delenv(SPAN_ID_ENV, raising=False)
    return log_dir


def _read_records(*, log_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in log_dir.glob("hooks-*.jsonl"):
        for line in path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


class TestAuditHookDecorator:
    def test_writes_body_record_on_success(self, audit_dir: Path) -> None:
        @audit_hook(name="my-hook", event="PreToolUse")
        def target() -> int:
            return 42

        result = target()
        assert result == 42
        records = _read_records(log_dir=audit_dir)
        assert len(records) == 1
        rec = records[0]
        assert rec["phase"] == "body"
        assert rec["hook"] == "my-hook"
        assert rec["event"] == "PreToolUse"
        assert rec["outcome"] == "ok"
        assert "body_ms" in rec
        assert "span_id" in rec

    def test_writes_body_record_on_sys_exit_0(self, audit_dir: Path) -> None:
        @audit_hook(name="my-hook")
        def target() -> None:
            import sys as _sys

            _sys.exit(0)

        with pytest.raises(SystemExit):
            target()

        records = _read_records(log_dir=audit_dir)
        assert len(records) == 1
        assert records[0]["outcome"] == "ok"

    def test_writes_body_record_on_sys_exit_2_as_block(self, audit_dir: Path) -> None:
        @audit_hook(name="my-hook")
        def target() -> None:
            import sys as _sys

            _sys.exit(2)

        with pytest.raises(SystemExit):
            target()

        records = _read_records(log_dir=audit_dir)
        assert records[0]["outcome"] == "block"

    def test_writes_body_record_on_exception_as_error(self, audit_dir: Path) -> None:
        @audit_hook(name="my-hook")
        def target() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            target()

        records = _read_records(log_dir=audit_dir)
        assert records[0]["outcome"] == "error"
        assert records[0]["error_type"] == "ValueError"

    def test_reuses_env_span_id(self, audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SPAN_ID_ENV, "abc123def456")

        @audit_hook(name="my-hook")
        def target() -> None:
            pass

        target()
        records = _read_records(log_dir=audit_dir)
        assert records[0]["span_id"] == "abc123def456"

    def test_disabled_via_env(self, audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUDIT_ENABLE_ENV, "0")

        @audit_hook(name="my-hook")
        def target() -> None:
            pass

        target()
        assert not audit_dir.exists() or not list(audit_dir.glob("*"))


class TestWrapRecord:
    def test_write_wrap_record(self, audit_dir: Path) -> None:
        write_wrap_record(
            hook="my-hook",
            argv=["python3", "script.py"],
            total_ms=150,
            exit_code=0,
            span_id="span1",
        )
        records = _read_records(log_dir=audit_dir)
        assert len(records) == 1
        rec = records[0]
        assert rec["phase"] == "wrap"
        assert rec["hook"] == "my-hook"
        assert rec["argv"] == ["python3", "script.py"]
        assert rec["total_ms"] == 150
        assert rec["exit_code"] == 0
        assert rec["span_id"] == "span1"

    def test_cli_wrap_record_writes_entry(self, audit_dir: Path) -> None:
        cli_wrap_record(argv=["my-hook", "span1", "100", "0", "child-arg"])
        records = _read_records(log_dir=audit_dir)
        assert len(records) == 1
        assert records[0]["hook"] == "my-hook"
        assert records[0]["total_ms"] == 100

    def test_cli_wrap_record_ignores_missing_args(self, audit_dir: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            cli_wrap_record(argv=["my-hook"])
        assert exc.value.code == 0
        assert not audit_dir.exists() or not list(audit_dir.glob("*"))

    def test_cli_wrap_record_ignores_nonint(self, audit_dir: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            cli_wrap_record(argv=["my-hook", "span1", "not-a-number", "0"])
        assert exc.value.code == 0
        assert not audit_dir.exists() or not list(audit_dir.glob("*"))


class TestNewWrapContext:
    def test_finish_wrap_records_timing(self, audit_dir: Path) -> None:
        span_id, start = new_wrap_context()
        time.sleep(0.01)
        finish_wrap_context(
            hook="my-hook",
            argv=["x"],
            span_id=span_id,
            start=start,
            exit_code=0,
        )
        records = _read_records(log_dir=audit_dir)
        assert len(records) == 1
        assert records[0]["total_ms"] >= 0


class TestIterRecords:
    def test_reads_from_log_dir(self, audit_dir: Path) -> None:
        write_wrap_record(
            hook="h1",
            argv=[],
            total_ms=10,
            exit_code=0,
            span_id="s1",
        )
        records = iter_records()
        assert len(records) == 1

    def test_filters_by_since(self, audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        write_wrap_record(
            hook="h1",
            argv=[],
            total_ms=10,
            exit_code=0,
            span_id="s1",
        )
        future = datetime.now(UTC) + timedelta(hours=1)
        records = iter_records(since=future)
        assert records == []


class TestSummarize:
    def test_joins_wrap_and_body(self, audit_dir: Path) -> None:
        @audit_hook(name="my-hook")
        def target() -> None:
            pass

        span_id, start = new_wrap_context()
        os.environ[SPAN_ID_ENV] = span_id
        try:
            target()
        finally:
            del os.environ[SPAN_ID_ENV]
        finish_wrap_context(
            hook="my-hook",
            argv=["x"],
            span_id=span_id,
            start=start,
            exit_code=0,
        )

        records = iter_records()
        stats = summarize(records=records)
        assert "my-hook" in stats
        assert stats["my-hook"]["count"] >= 1
        assert stats["my-hook"]["paired_count"] == 1

    def test_counts_blocks_and_errors(self, audit_dir: Path) -> None:
        @audit_hook(name="h")
        def ok() -> None:
            pass

        @audit_hook(name="h")
        def blocks() -> None:
            import sys as _sys

            _sys.exit(2)

        @audit_hook(name="h")
        def errs() -> None:
            raise RuntimeError("x")

        ok()
        with pytest.raises(SystemExit):
            blocks()
        with pytest.raises(RuntimeError):
            errs()

        stats = summarize(records=iter_records())
        assert stats["h"]["block_count"] == 1
        assert stats["h"]["error_count"] == 1


class TestPrune:
    def test_removes_old_files(self, audit_dir: Path) -> None:
        audit_dir.mkdir(parents=True)
        old = audit_dir / "hooks-2020-01-01.jsonl"
        old.write_text('{"phase":"wrap"}\n')
        old_mtime = time.time() - 365 * 86400
        os.utime(old, (old_mtime, old_mtime))

        fresh = audit_dir / "hooks-9999-12-31.jsonl"
        fresh.write_text('{"phase":"wrap"}\n')

        deleted = prune(retain_days=30)
        assert deleted == 1
        assert not old.exists()
        assert fresh.exists()

    def test_respects_retain_env(self, audit_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUDIT_RETAIN_ENV, "1")
        audit_dir.mkdir(parents=True)
        old = audit_dir / "hooks-2020-01-01.jsonl"
        old.write_text("")
        old_mtime = time.time() - 10 * 86400
        os.utime(old, (old_mtime, old_mtime))

        deleted = prune()
        assert deleted == 1
