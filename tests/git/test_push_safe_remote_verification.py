"""GH-1099: a push wrapper reports the state that resulted, not the call.

`git push` exiting 0 is the local process's account of a network
exchange. The worked failure is a crew worker whose `update_pr` was
silently lost mid-transport — the payload said nothing, and only the
worker's own re-read caught it. These tests drive the real script
against a local bare repo so the emitted JSON is checked, not assumed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "git" / "scripts" / "git-push-safe.sh"

_GIT_IDENTITY = [
    ["git", "config", "user.email", "test@example.com"],
    ["git", "config", "user.name", "Test"],
]


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=30
    )


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> Path:
    """A working repo whose `origin` is a local bare repo."""
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
        timeout=30,
    )

    work = tmp_path / "work"
    work.mkdir()
    git("init", "-b", "feature", cwd=work)
    for identity in _GIT_IDENTITY:
        subprocess.run(identity, cwd=work, capture_output=True, check=True, timeout=30)
    (work / "file.txt").write_text("content\n")
    git("add", "-A", cwd=work)
    git("commit", "-m", "seed", cwd=work)
    git("remote", "add", "origin", str(bare), cwd=work)
    return work


def push(repo: Path, *args: str) -> dict:
    result = subprocess.run(
        [str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestRemoteVerification:
    def test_a_successful_push_is_confirmed_against_the_remote(self, repo_with_remote: Path):
        payload = push(repo_with_remote, "origin", "feature")

        assert payload["pushed"] is True
        assert payload["remote_verified"] is True

    def test_the_confirmed_sha_is_the_one_that_was_pushed(self, repo_with_remote: Path):
        expected = git("rev-parse", "feature", cwd=repo_with_remote).stdout.strip()

        payload = push(repo_with_remote, "origin", "feature")

        assert payload["remote_sha"] == expected

    def test_the_short_sha_still_describes_the_pushed_ref(self, repo_with_remote: Path):
        payload = push(repo_with_remote, "origin", "feature")
        expected = git("rev-parse", "--short", "feature", cwd=repo_with_remote).stdout.strip()

        assert payload["sha"] == expected

    def test_setting_upstream_does_not_swallow_the_payload(self, repo_with_remote: Path):
        # `git push -u` announces the tracking setup on STDOUT. The
        # wrapper json.loads this script's whole stdout and falls back to
        # `{}` on failure, so that one line silently replaced every
        # payload — and `-u` is the shape every first push uses, which is
        # when a caller most needs the confirmation.
        payload = push(repo_with_remote, "-u", "origin", "feature")

        assert payload["pushed"] is True
        assert payload["remote_verified"] is True

    def test_a_second_push_of_new_work_reconfirms(self, repo_with_remote: Path):
        push(repo_with_remote, "origin", "feature")
        (repo_with_remote / "file.txt").write_text("more\n")
        git("add", "-A", cwd=repo_with_remote)
        git("commit", "-m", "second", cwd=repo_with_remote)

        payload = push(repo_with_remote, "origin", "feature")

        assert payload["remote_verified"] is True
        assert (
            payload["remote_sha"]
            == git("rev-parse", "feature", cwd=repo_with_remote).stdout.strip()
        )
