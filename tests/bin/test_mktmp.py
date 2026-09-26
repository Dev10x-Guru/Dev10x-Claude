"""Tests for bin/mktmp.sh portable-mktemp behavior (GH-1467).

bin/mktmp.sh delegated straight to GNU-only mktemp flags
(--dry-run, --tmpdir=) and put the X placeholders mid-template, ahead
of the extension. GNU mktemp tolerates both; BSD mktemp (macOS) does
neither: unrecognised long flags are consumed as extra template
arguments rather than rejected, and only a *trailing* run of X's is
substituted. The net effect on macOS was a literal
"prefix.XXXXXXXXXXXX.ext" path that does not exist and collides
across calls with the same prefix.

These tests run on Linux CI (where GNU mktemp accepts -d/-p/-u just
as well as the long forms), so they guard the portable flag spelling
and the trailing-X template shape rather than reproducing the BSD
failure directly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = _REPO_ROOT / "bin" / "mktmp.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestMktmpPortableFlags:
    def test_no_gnu_only_long_flags_in_mktemp_invocations(self) -> None:
        invocation_lines = [
            line for line in SCRIPT.read_text().splitlines() if line.strip().startswith("mktemp ")
        ]
        assert invocation_lines, "expected at least one mktemp invocation line"
        for line in invocation_lines:
            assert "--dry-run" not in line
            assert "--tmpdir=" not in line

    def test_x_placeholders_are_trailing_in_template(self) -> None:
        content = SCRIPT.read_text()
        assert 'TEMPLATE="${PREFIX}${EXT}.XXXXXXXXXXXX"' in content


class TestMktmpDryRunPath:
    def test_returns_expanded_path_not_literal_template(self) -> None:
        result = _run("git", "gh1467-regression", ".txt")
        assert result.returncode == 0, result.stderr
        path = result.stdout.strip()
        assert "XXXXXXXXXXXX" not in path
        assert path.startswith("/tmp/Dev10x/git/gh1467-regression.txt.")

    def test_two_calls_with_same_prefix_do_not_collide(self) -> None:
        first = _run("git", "gh1467-collision", ".txt").stdout.strip()
        second = _run("git", "gh1467-collision", ".txt").stdout.strip()
        assert first != second

    def test_dry_run_path_is_not_created(self) -> None:
        path = Path(_run("git", "gh1467-nocreate", ".txt").stdout.strip())
        assert not path.exists()


class TestMktmpCreateFile:
    def test_create_flag_creates_expanded_path(self) -> None:
        result = _run("--create", "git", "gh1467-create", ".txt")
        assert result.returncode == 0, result.stderr
        path = Path(result.stdout.strip())
        assert "XXXXXXXXXXXX" not in str(path)
        assert path.exists()
        path.unlink()


class TestMktmpDirMode:
    def test_dir_flag_creates_expanded_directory(self) -> None:
        result = _run("-d", "git", "gh1467-dir")
        assert result.returncode == 0, result.stderr
        path = Path(result.stdout.strip())
        assert "XXXXXXXXXXXX" not in str(path)
        assert path.is_dir()
        path.rmdir()
