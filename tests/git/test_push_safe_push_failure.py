from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev10x.coding.git import push_safe
from dev10x.core.domain.common.result import ErrorResult
from dev10x.core.subprocess_utils import use_cwd

_SCRIPT = Path(__file__).parents[2] / "skills" / "git" / "scripts" / "git-push-safe.sh"
_TIMEOUT_SECONDS = 30
_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    ).stdout.strip()


def _commit(name: str, *, cwd: Path) -> None:
    (cwd / f"{name}.txt").write_text(name, encoding="utf-8")
    _git("add", "-A", cwd=cwd)
    _git("commit", "-q", "-m", name, cwd=cwd)


def _run(*args: str, cwd: Path) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    return result.returncode, json.loads(result.stdout.strip()), result.stderr


@pytest.fixture()
def pushed_feature(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)],
        check=True,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(work)],
        check=True,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    _git("config", "user.name", "test", cwd=work)
    _git("config", "user.email", "test@example.com", cwd=work)
    _commit("root", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-q", "-u", "origin", "main", cwd=work)
    _git("checkout", "-q", "-b", "feature", cwd=work)
    _commit("feature", cwd=work)
    _git("push", "-q", "-u", "origin", "feature", cwd=work)
    _git("commit", "-q", "--amend", "-m", "feature rewritten", cwd=work)
    return work


@pytest.fixture()
def stale_lease(pushed_feature: Path) -> Path:
    _git("update-ref", "-d", "refs/remotes/origin/feature", cwd=pushed_feature)
    return pushed_feature


class TestARejectedPushReportsFailure:
    def test_a_rejected_lease_exits_non_zero(self, stale_lease: Path) -> None:
        returncode, payload, _ = _run("--force-with-lease", "origin", "feature", cwd=stale_lease)

        assert returncode != 0
        assert payload == {
            "pushed": False,
            "ref": "feature",
            "remote": "origin",
            "blocked_reason": "push_failed",
        }

    def test_a_rejected_lease_carries_gits_reason_on_stderr(self, stale_lease: Path) -> None:
        _, _, stderr = _run("--force-with-lease", "origin", "feature", cwd=stale_lease)

        assert "stale info" in stderr

    @pytest.mark.asyncio
    async def test_push_safe_surfaces_gits_reason_as_an_error(self, stale_lease: Path) -> None:
        with use_cwd(str(stale_lease)):
            result = await push_safe(args=["--force-with-lease", "origin", "feature"])

        assert isinstance(result, ErrorResult)
        assert "stale info" in result.error


class TestFlagPositionDoesNotMatter:
    @pytest.mark.parametrize(
        "args",
        [
            ("--force-with-lease", "origin", "feature"),
            ("origin", "feature", "--force-with-lease"),
        ],
        ids=["flags-first", "flags-last"],
    )
    def test_a_lease_pushes_with_the_flag_on_either_side(
        self, pushed_feature: Path, args: tuple[str, ...]
    ) -> None:
        returncode, payload, _ = _run(*args, cwd=pushed_feature)

        assert returncode == 0
        assert payload["pushed"] is True
        assert payload["remote_verified"] is True
