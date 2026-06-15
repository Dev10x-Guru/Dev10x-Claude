"""Tests for precompact-context.py hook."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = _REPO_ROOT / "hooks" / "scripts" / "precompact-context.py"


def _run_hook(*, payload: dict | None = None) -> subprocess.CompletedProcess[str]:
    stdin_data = json.dumps(payload or {})
    return subprocess.run(
        [str(HOOK)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestPrecompactContext:
    def test_exits_successfully(self) -> None:
        result = _run_hook()
        assert result.returncode == 0

    def test_outputs_valid_json(self) -> None:
        result = _run_hook()
        output = json.loads(result.stdout)
        assert "hookSpecificOutput" in output
        assert "systemMessage" in output["hookSpecificOutput"]

    def test_includes_branch_info(self) -> None:
        result = _run_hook()
        output = json.loads(result.stdout)
        message = output["hookSpecificOutput"]["systemMessage"]
        assert "Branch:" in message

    def test_includes_working_directory(self) -> None:
        result = _run_hook()
        output = json.loads(result.stdout)
        message = output["hookSpecificOutput"]["systemMessage"]
        assert "Working directory:" in message

    def test_includes_recent_commits(self) -> None:
        result = _run_hook()
        output = json.loads(result.stdout)
        message = output["hookSpecificOutput"]["systemMessage"]
        assert "Recent commits" in message

    def test_includes_essential_conventions(self) -> None:
        result = _run_hook()
        output = json.loads(result.stdout)
        message = output["hookSpecificOutput"]["systemMessage"]
        assert "Essential Conventions" in message

    def test_includes_recovery_header(self) -> None:
        result = _run_hook()
        output = json.loads(result.stdout)
        message = output["hookSpecificOutput"]["systemMessage"]
        assert "Post-Compaction Context Recovery" in message


class TestDrainStdin:
    def test_consumes_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.hooks.session_dispatch import drain_stdin

        monkeypatch.setattr(sys, "stdin", io.StringIO("hook payload"))
        drain_stdin()

        assert sys.stdin.read() == ""

    def test_swallows_read_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dev10x.hooks.session_dispatch import drain_stdin

        class _Boom:
            def read(self) -> str:
                raise ValueError("stdin closed")

        monkeypatch.setattr(sys, "stdin", _Boom())
        drain_stdin()
