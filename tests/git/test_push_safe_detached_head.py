"""push_safe must never report a ref that names nothing (GH-1285).

With no refspec on the command line the script guessed the target from
``git rev-parse --abbrev-ref HEAD``. That answers the literal string
``HEAD`` on a detached HEAD, and the surrounding fallback answered ``""``
when it failed outright — so every JSON payload could carry
``"ref": ""``: syntactically valid, and carrying no information about
what was or was not pushed.

The script is driven against a real repository rather than a mock,
because the defect is in how git resolves a ref.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

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


def _payload(*args: str, cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_ENV,
        timeout=_TIMEOUT_SECONDS,
    )
    payload = json.loads(result.stdout.strip())
    payload["stderr"] = result.stderr
    payload["returncode"] = result.returncode
    return payload


@pytest.fixture()
def detached_checkout(tmp_path: Path) -> Path:
    """A clone sitting on a commit rather than a branch."""
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
    (work / "root.txt").write_text("root", encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "root", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    _git("push", "-q", "-u", "origin", "main", cwd=work)
    _git("checkout", "-q", "--detach", "HEAD", cwd=work)
    return work


class TestDetachedHead:
    def test_a_bare_push_is_refused(self, detached_checkout: Path) -> None:
        payload = _payload(cwd=detached_checkout)

        assert payload["pushed"] is False
        assert payload["blocked_reason"] == "detached_head"

    def test_the_reported_ref_names_the_commit(self, detached_checkout: Path) -> None:
        # The point of the fix: the payload identifies where HEAD actually
        # is, so a caller reading only the JSON can act on it.
        expected = _git("rev-parse", "--short", "HEAD", cwd=detached_checkout)

        payload = _payload(cwd=detached_checkout)

        assert payload["ref"] == expected

    def test_the_refusal_exits_non_zero(self, detached_checkout: Path) -> None:
        assert _payload(cwd=detached_checkout)["returncode"] != 0

    def test_an_explicit_refspec_still_pushes(self, detached_checkout: Path) -> None:
        # Detachment is only unresolvable when the target has to be
        # guessed; naming it leaves nothing to guess.
        payload = _payload("origin", "HEAD:main", cwd=detached_checkout)

        assert payload["pushed"] is True
        assert payload["ref"] == "main"
