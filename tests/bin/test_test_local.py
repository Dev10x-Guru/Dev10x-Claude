"""Tests for bin/test-local.sh — the local dev-release smoke tool."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = _REPO_ROOT / "bin" / "test-local.sh"


def _run(
    *,
    args: list[str],
    home: Path,
) -> subprocess.CompletedProcess[str]:
    run_env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=run_env,
        cwd=str(_REPO_ROOT),
    )


class TestSyntax:
    def test_bash_syntax_is_valid(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


class TestHelp:
    def test_help_exits_zero(self, tmp_path: Path) -> None:
        result = _run(args=["--help"], home=tmp_path)
        assert result.returncode == 0, result.stderr

    def test_help_documents_flags(self, tmp_path: Path) -> None:
        result = _run(args=["--help"], home=tmp_path)
        assert "--keep" in result.stdout
        assert "--no-verify" in result.stdout

    def test_help_makes_no_writes_under_home_claude(self, tmp_path: Path) -> None:
        _run(args=["--help"], home=tmp_path)
        assert not (tmp_path / ".claude").exists()


class TestArgValidation:
    def test_unknown_arg_exits_one(self, tmp_path: Path) -> None:
        result = _run(args=["--bogus"], home=tmp_path)
        assert result.returncode == 1
        assert "Unknown argument" in result.stderr

    def test_unknown_arg_makes_no_writes_under_home_claude(self, tmp_path: Path) -> None:
        _run(args=["--bogus"], home=tmp_path)
        assert not (tmp_path / ".claude").exists()
