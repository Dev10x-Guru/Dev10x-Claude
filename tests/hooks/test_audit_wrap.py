"""Tests for hooks/scripts/audit-wrap (GH-1447).

`audit-wrap` prefixes every entry in `hooks/hooks.json` — per
`.claude/rules/hook-patterns.md` it captures total wall-clock timing
and injects `DEV10X_HOOK_SPAN_ID` so body-phase records correlate
with wrap-phase records. It had zero test coverage: a grep found it
only as a path-string literal in an unrelated permission-noise
fixture, never subprocess-invoked. This mirrors the subprocess-test
pattern `TestPluginLoadGuard` already uses for
`hooks/scripts/plugin-load-guard.sh` in `test_orchestrators.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "hooks" / "scripts"
AUDIT_WRAP = SCRIPTS / "audit-wrap"


def _run_wrap(
    *,
    hook: str,
    child_args: list[str],
    audit_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "DEV10X_HOOK_AUDIT_DIR": str(audit_dir),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["sh", str(AUDIT_WRAP), hook, *child_args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _read_records(audit_dir: Path) -> list[dict]:
    log_files = sorted(audit_dir.glob("hooks-*.jsonl"))
    if not log_files:
        return []
    records = []
    for log_file in log_files:
        for line in log_file.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


class TestExitCodePassthrough:
    def test_zero_exit_passes_through(self, tmp_path: Path) -> None:
        result = _run_wrap(hook="test-hook", child_args=["true"], audit_dir=tmp_path)
        assert result.returncode == 0

    def test_nonzero_exit_passes_through_unchanged(self, tmp_path: Path) -> None:
        result = _run_wrap(hook="test-hook", child_args=["sh", "-c", "exit 7"], audit_dir=tmp_path)
        assert result.returncode == 7

    def test_missing_command_errors(self, tmp_path: Path) -> None:
        result = _run_wrap(hook="test-hook", child_args=[], audit_dir=tmp_path)
        assert result.returncode == 2
        assert "missing command" in result.stderr


class TestStdinPassthrough:
    def test_stdin_reaches_the_child_unchanged(self, tmp_path: Path) -> None:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", ""),
            "DEV10X_HOOK_AUDIT_DIR": str(tmp_path),
        }
        result = subprocess.run(
            ["sh", str(AUDIT_WRAP), "test-hook", "cat"],
            input="payload-content\n",
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert result.returncode == 0
        assert result.stdout == "payload-content\n"


class TestSpanIdPropagation:
    def test_span_id_is_minted_and_exported_when_absent(self, tmp_path: Path) -> None:
        result = _run_wrap(
            hook="test-hook",
            child_args=["sh", "-c", "printf '%s' \"$DEV10X_HOOK_SPAN_ID\""],
            audit_dir=tmp_path,
        )
        assert result.returncode == 0
        assert result.stdout.strip() != ""

    def test_existing_span_id_is_reused_not_reminted(self, tmp_path: Path) -> None:
        result = _run_wrap(
            hook="test-hook",
            child_args=["sh", "-c", "printf '%s' \"$DEV10X_HOOK_SPAN_ID\""],
            audit_dir=tmp_path,
            extra_env={"DEV10X_HOOK_SPAN_ID": "fixed-span-abc123"},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "fixed-span-abc123"

    def test_span_id_correlates_wrap_record(self, tmp_path: Path) -> None:
        result = _run_wrap(
            hook="test-hook",
            child_args=["true"],
            audit_dir=tmp_path,
            extra_env={"DEV10X_HOOK_SPAN_ID": "fixed-span-xyz789"},
        )
        assert result.returncode == 0
        records = _read_records(tmp_path)
        assert len(records) == 1
        assert records[0]["span_id"] == "fixed-span-xyz789"


class TestJsonlRecordShape:
    def test_wrap_record_has_the_expected_shape(self, tmp_path: Path) -> None:
        result = _run_wrap(hook="my-test-hook", child_args=["true"], audit_dir=tmp_path)
        assert result.returncode == 0
        records = _read_records(tmp_path)
        assert len(records) == 1
        record = records[0]
        assert record["phase"] == "wrap"
        assert record["hook"] == "my-test-hook"
        assert isinstance(record["span_id"], str) and record["span_id"]
        assert isinstance(record["total_ms"], int)
        assert record["total_ms"] >= 0
        assert record["exit_code"] == 0
        assert "ts" in record
        assert "outcome" in record

    def test_wrap_record_carries_the_failing_exit_code(self, tmp_path: Path) -> None:
        result = _run_wrap(
            hook="my-test-hook", child_args=["sh", "-c", "exit 3"], audit_dir=tmp_path
        )
        assert result.returncode == 3
        records = _read_records(tmp_path)
        assert len(records) == 1
        assert records[0]["exit_code"] == 3


class TestAuditDisabled:
    @pytest.mark.parametrize("disable_value", ["0", "false", "no", "off"])
    def test_disabled_flag_skips_the_log_write(self, tmp_path: Path, disable_value: str) -> None:
        result = _run_wrap(
            hook="test-hook",
            child_args=["true"],
            audit_dir=tmp_path,
            extra_env={"DEV10X_HOOK_AUDIT": disable_value},
        )
        assert result.returncode == 0
        assert _read_records(tmp_path) == []

    def test_disabled_flag_still_passes_through_a_failing_exit_code(self, tmp_path: Path) -> None:
        result = _run_wrap(
            hook="test-hook",
            child_args=["sh", "-c", "exit 5"],
            audit_dir=tmp_path,
            extra_env={"DEV10X_HOOK_AUDIT": "0"},
        )
        assert result.returncode == 5
        assert _read_records(tmp_path) == []
