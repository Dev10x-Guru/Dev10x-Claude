"""Tests for finding the session that owns an artifact (GH-1938)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

import pytest
from dev10x.domain.common.result import err, ok

from dev10x.comm.overwatch import owner as owner_module
from dev10x.comm.overwatch.owner import (
    MAX_HOPS,
    ArtifactOwner,
    find_owner,
    parent_pid,
)
from dev10x.comm.overwatch.probes import ProbeError
from dev10x.comm.overwatch.sessions import ClaudeSession

SESSIONS = [
    ClaudeSession(
        session_id="sid-a", pid=500, name="alpha", cwd="/a", status="busy", waiting_for=""
    ),
    ClaudeSession(
        session_id="sid-b", pid=600, name="beta", cwd="/b", status="idle", waiting_for=""
    ),
    ClaudeSession(
        session_id="sid-c", pid=700, name="beta", cwd="/c", status="idle", waiting_for=""
    ),
]
ALPHA = ArtifactOwner(session_id="sid-a", name="alpha", cwd="/a")
CHAIN = {100: 200, 200: 300, 300: 500}
NOT_FOUND = err(
    "Could not find the Claude session that ran this among its parent processes; "
    "pass --session NAME_OR_ID."
)


def _runner(*, stdout: str = "", error: Exception | None = None) -> Callable[..., Any]:
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if error is not None:
            raise error
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout)

    return run


class TestParentPid:
    @pytest.mark.parametrize(
        ("runner", "expected"),
        [
            (_runner(stdout="  4242\n"), 4242),
            (_runner(stdout=""), None),
            (_runner(error=FileNotFoundError("ps")), None),
            (_runner(error=subprocess.TimeoutExpired(cmd="ps", timeout=5)), None),
        ],
        ids=["found", "gone", "no-ps", "timeout"],
    )
    def test_reads_ps(self, runner: Callable[..., Any], expected: int | None) -> None:
        assert parent_pid(pid=100, runner=runner) == expected

    def test_asks_ps_for_the_parent_with_a_timeout(self) -> None:
        calls: list[dict[str, Any]] = []

        def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append({"args": args, "timeout": kwargs["timeout"]})
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="1")

        parent_pid(pid=100, runner=run)

        assert calls == [{"args": ["ps", "-o", "ppid=", "-p", "100"], "timeout": 5}]


class TestFindOwner:
    def _find(self, *, start_pid: int = 100, session: str = "") -> object:
        return find_owner(
            start_pid=start_pid,
            session=session,
            sessions_reader=lambda: SESSIONS,
            parent_of=CHAIN.get,
        )

    def test_walks_up_to_the_session(self) -> None:
        assert self._find() == ok(ALPHA)

    @pytest.mark.parametrize("start_pid", [999, 1], ids=["orphan-chain", "init"])
    def test_no_ancestor_names_the_override(self, start_pid: int) -> None:
        assert self._find(start_pid=start_pid) == NOT_FOUND

    def test_stops_after_max_hops(self) -> None:
        asked: list[int] = []

        def endless(pid: int) -> int:
            asked.append(pid)
            return pid + 1

        result = find_owner(start_pid=10_000, sessions_reader=lambda: SESSIONS, parent_of=endless)

        assert (result, len(asked)) == (NOT_FOUND, MAX_HOPS)

    def test_default_lookup_asks_ps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(owner_module, "parent_pid", lambda pid: CHAIN.get(pid))

        assert find_owner(start_pid=100, sessions_reader=lambda: SESSIONS) == ok(ALPHA)

    @pytest.mark.parametrize("wanted", ["alpha", "sid-a"])
    def test_session_override(self, wanted: str) -> None:
        assert self._find(session=wanted) == ok(ALPHA)

    @pytest.mark.parametrize(
        ("wanted", "error"),
        [
            (
                "ghost",
                'No running Claude session is named "ghost" or has that id; check --session.',
            ),
            ("beta", 'Several sessions are named "beta"; pass --session with the session id.'),
        ],
    )
    def test_session_override_errors(self, wanted: str, error: str) -> None:
        assert self._find(session=wanted) == err(error)

    def test_probe_failure(self) -> None:
        def broken() -> list[ClaudeSession]:
            raise ProbeError("claude is not installed")

        result = find_owner(start_pid=100, sessions_reader=broken)

        assert result == err("Could not list Claude sessions: claude is not installed")

    def test_owner_as_dict(self) -> None:
        assert ALPHA.to_dict() == {"session_id": "sid-a", "name": "alpha", "cwd": "/a"}
