from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev10x.ci_review import process
from dev10x.ci_review.process import run_checked
from dev10x.core.domain.common.result import ErrorResult, SuccessResult


def test_success_returns_stdout(tmp_path: Path) -> None:
    assert run_checked(args=["pwd"], cwd=tmp_path) == SuccessResult(value=f"{tmp_path}\n")


def test_nonzero_exit_carries_stderr() -> None:
    result = run_checked(args=["ls", "/definitely/not/here", "a", "b", "c"])

    assert isinstance(result, ErrorResult)
    assert result.error.startswith("`ls /definitely/not/here a b …` exited")
    assert result.details["stderr"]


def test_missing_binary() -> None:
    result = run_checked(args=["dev10x-no-such-binary"])

    assert isinstance(result, ErrorResult)
    assert "could not start" in result.error


def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **_: Any) -> None:
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(process.subprocess_utils, "run", fake_run)

    result = run_checked(args=["sleep", "9"], timeout=1)

    assert isinstance(result, ErrorResult)
    assert "timed out after 1s. Please try again." in result.error
