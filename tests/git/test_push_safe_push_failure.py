"""A push git rejects must exit non-zero and keep git's reason (GH-1734).

`git-push-safe.sh` captured the status as `if ! git push ...; then rc=$?`.
Inside that branch `$?` is the status of the negation, always 0, so a
rejected push exited 0. `_run_git_script` reads exit 0 as success and
returned the bare `push_failed` payload, dropping git's stderr — the one
line that says why.

Driven against real repositories: a stale lease is how git itself
rejects the push, and a mock would only agree with whatever it was told.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult

from dev10x.git import push_safe
from dev10x.subprocess_utils import use_cwd

_SCRIPT = Path(__file__).parents[2] / "skills" / "git" / "scripts" / "git-push-safe.sh"
_TIMEOUT_SECONDS = 30
_STALE_LEASE = "stale info"


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    # On os.environ rather than an `env=` argument: push_safe() reaches the
    # script through subprocess_utils, which forwards no env of its own.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        timeout=_TIMEOUT_SECONDS,
    ).stdout.strip()


@pytest.fixture()
def stale_lease_repo(tmp_path: Path) -> Path:
    """A feature branch whose lease has nothing to compare against.

    Deleting the remote-tracking ref after an amend is the issue's own
    repro: `--force-with-lease` then has no expected value and git
    refuses with `(stale info)`.
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)],
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    subprocess.run(
        ["git", "init", "-q", "-b", "feature", str(work)],
        check=True,
        timeout=_TIMEOUT_SECONDS,
    )
    _git("config", "user.name", "test", cwd=work)
    _git("config", "user.email", "test@example.com", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "root", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-q", "-u", "origin", "feature", cwd=work)
    _git("commit", "-q", "--amend", "-m", "rewritten root", cwd=work)
    _git("update-ref", "-d", "refs/remotes/origin/feature", cwd=work)
    return work


@pytest.fixture()
def script_result(stale_lease_repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_SCRIPT), "--force-with-lease", "origin", "feature"],
        capture_output=True,
        text=True,
        cwd=stale_lease_repo,
        timeout=_TIMEOUT_SECONDS,
    )


async def _push_safe(*, repo: Path) -> object:
    with use_cwd(str(repo)):
        return await push_safe(args=["--force-with-lease", "origin", "feature"])


class TestTheScriptOnARejectedPush:
    def test_exits_non_zero(self, script_result: subprocess.CompletedProcess[str]) -> None:
        assert script_result.returncode != 0

    def test_keeps_the_push_failed_payload(
        self, script_result: subprocess.CompletedProcess[str]
    ) -> None:
        payload = json.loads(script_result.stdout.strip())

        assert payload == {
            "pushed": False,
            "ref": "feature",
            "remote": "origin",
            "blocked_reason": "push_failed",
        }

    def test_puts_gits_reason_on_stderr(
        self, script_result: subprocess.CompletedProcess[str]
    ) -> None:
        assert _STALE_LEASE in script_result.stderr


class TestPushSafeOnARejectedPush:
    @pytest.mark.asyncio
    async def test_returns_an_error_result(self, stale_lease_repo: Path) -> None:
        result = await _push_safe(repo=stale_lease_repo)

        assert isinstance(result, ErrorResult)

    @pytest.mark.asyncio
    async def test_the_error_carries_gits_reason(self, stale_lease_repo: Path) -> None:
        result = await _push_safe(repo=stale_lease_repo)

        assert _STALE_LEASE in result.error
