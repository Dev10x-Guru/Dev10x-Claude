"""verify-state.sh extracts the ticket key from any branch shape (GH-1680 F3).

``cut -d/ -f2`` turned ``feature/ACME-1925-roadrunner-sms`` into
``ACME-1925-roadrunner-sms``, which then went into the PR title and the
``Fixes:`` trailer as if it were a ticket key.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "gh-pr-create" / "scripts" / "verify-state.sh"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", str(origin), str(work), cwd=tmp_path)
    _git("commit", "--allow-empty", "-m", "root", cwd=work)
    _git("push", "origin", "HEAD:main", "HEAD:develop", cwd=work)
    _git("fetch", "origin", cwd=work)
    return work


def _issue_for(*, clone: Path, branch: str) -> str:
    _git("checkout", "-b", branch, "origin/develop", cwd=clone)
    _git("commit", "--allow-empty", "-m", "work", cwd=clone)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=clone,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
    return lines["ISSUE"]


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("feature/ACME-1925-roadrunner-sms", "ACME-1925"),
        ("janusz/GH-1680/fix-ticket-key", "GH-1680"),
        ("janusz/PAY-32/wt-3/multi-location", "PAY-32"),
        ("ACME-7-top-level", "ACME-7"),
        ("janusz/self-motivated-cleanup", "self-motivated-cleanup"),
    ],
)
def test_ticket_key_is_extracted_from_branch(clone: Path, branch: str, expected: str) -> None:
    assert _issue_for(clone=clone, branch=branch) == expected
