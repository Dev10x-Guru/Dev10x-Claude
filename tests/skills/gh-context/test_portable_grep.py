"""Shipped shell scripts must run under BSD grep (GH-1492).

macOS grep has no ``-P``. ``gh-issue-create.sh`` extracted the issue
number with ``grep -oP`` *after* ``gh issue create`` succeeded, so under
``set -euo pipefail`` every created issue was reported as an error — and a
caller retrying on ``failed`` filed each one twice. ``gh-pr-get.sh`` used
the same flag behind ``|| true``, so its unknown-field fallback silently
never fired.

The end-to-end cases put a stub ``grep`` that rejects ``-P`` ahead of the
real one on ``PATH``, which is what a Mac does to these scripts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "skills" / "gh-context" / "scripts"

PCRE_GREP = re.compile(r"\bgrep\b[^|;&\n]*\s(?:-[A-Za-z]*P[A-Za-z]*|--perl-regexp)\b")

REAL_GREP = shutil.which("grep")

BSD_GREP = (
    "#!/usr/bin/env bash\n"
    'for arg in "$@"; do\n'
    '  case "$arg" in\n'
    "    --perl-regexp|-*P*)\n"
    '      [[ "$arg" == --* && "$arg" != --perl-regexp ]] && continue\n'
    '      echo "grep: invalid option -- P" >&2; exit 2 ;;\n'
    "  esac\n"
    "done\n"
    f'exec {REAL_GREP} "$@"\n'
)

STUB_GH_ISSUE = (
    "#!/usr/bin/env bash\n"
    'case "$1 $2" in\n'
    '  "issue create") cat "${FAKE_GH_DIR}/create_stdout.txt" ;;\n'
    '  "issue view") printf \'{"number": %s, "title": "t", "url": "u"}\\n\' "$3" ;;\n'
    "  *) exit 99 ;;\n"
    "esac\n"
)

STUB_GH_PR = (
    "#!/usr/bin/env bash\n"
    'fields="${@: -1}"\n'
    'case ",$fields," in\n'
    "  *,files,*) echo 'Unknown JSON field: \"files\"' >&2; exit 1 ;;\n"
    "esac\n"
    'printf \'{"number": %s}\\n\' "$3"\n'
)


def _shipped_shell_scripts() -> list[Path]:
    return sorted((REPO_ROOT / "skills").glob("**/*.sh"))


def _install(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(
    tmp_path: Path,
    *,
    script: str,
    args: list[str],
    stub_gh: str,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _install(bin_dir=bin_dir, name="gh", body=stub_gh)
    _install(bin_dir=bin_dir, name="grep", body=BSD_GREP)
    return subprocess.run(
        ["bash", str(SCRIPTS_DIR / script), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_GH_DIR": str(tmp_path),
        },
    )


class TestNoPcreGrepInShippedScripts:
    def test_scan_covers_the_gh_context_scripts(self) -> None:
        assert SCRIPTS_DIR / "gh-issue-create.sh" in _shipped_shell_scripts()

    @pytest.mark.parametrize(
        "line",
        [
            "NUMBER=$(echo \"$URL\" | grep -oP '/issues/\\K[0-9]+$')",
            "grep -P 'x' file",
            "grep --perl-regexp 'x' file",
        ],
    )
    def test_detector_flags_pcre_grep(self, line: str) -> None:
        assert PCRE_GREP.search(line)

    @pytest.mark.parametrize(
        "line",
        [
            'grep -vxF "$UNKNOWN_FIELD"',
            "grep -oE '[0-9]+'",
            "sed -nE 's/P//p'",
        ],
    )
    def test_detector_ignores_portable_grep(self, line: str) -> None:
        assert PCRE_GREP.search(line) is None

    def test_no_shipped_script_uses_grep_p(self) -> None:
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
            for path in _shipped_shell_scripts()
            for number, line in enumerate(path.read_text().splitlines(), start=1)
            if not line.lstrip().startswith("#") and PCRE_GREP.search(line)
        ]
        assert offenders == [], "BSD grep (macOS) has no -P:\n" + "\n".join(offenders)


class TestIssueCreateUnderBsdGrep:
    def test_created_issue_is_reported_as_created(self, tmp_path: Path) -> None:
        (tmp_path / "create_stdout.txt").write_text("https://github.com/o/r/issues/42\n")
        result = _run(
            tmp_path,
            script="gh-issue-create.sh",
            args=["title", "--repo", "o/r"],
            stub_gh=STUB_GH_ISSUE,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["number"] == 42

    def test_number_comes_from_the_url_line_amid_other_output(self, tmp_path: Path) -> None:
        (tmp_path / "create_stdout.txt").write_text(
            "Creating issue in o/r\n\nhttps://github.com/o/r/issues/7\n"
        )
        result = _run(
            tmp_path,
            script="gh-issue-create.sh",
            args=["title", "--repo", "o/r"],
            stub_gh=STUB_GH_ISSUE,
        )
        assert json.loads(result.stdout)["number"] == 7

    def test_unparseable_output_fails_loudly(self, tmp_path: Path) -> None:
        (tmp_path / "create_stdout.txt").write_text("https://github.com/o/r/pull/7\n")
        result = _run(
            tmp_path,
            script="gh-issue-create.sh",
            args=["title", "--repo", "o/r"],
            stub_gh=STUB_GH_ISSUE,
        )
        assert result.returncode == 1
        assert "no issue number" in result.stderr


class TestPrGetUnderBsdGrep:
    def test_unknown_field_fallback_still_fires(self, tmp_path: Path) -> None:
        result = _run(
            tmp_path,
            script="gh-pr-get.sh",
            args=["5", "o/r"],
            stub_gh=STUB_GH_PR,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"number": 5}
        assert "rejects 'files'" in result.stderr
