"""Tests for the SessionStart reload context builder (GH-545).

Repointed from the removed ``session-start-reload.py`` shim to the live
in-process path: ``dev10x.hooks.session.build_reload_context``. The
``session-start.py`` orchestrator invokes this directly as the
``session-reload`` feature (GH-959), so it is the function that actually
runs at SessionStart — the standalone shim was unwired dead code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.session_document import state_path_for_toplevel, write_state
from dev10x.hooks import session, session_dispatch


def _write_state(*, toplevel: str, session_id: str) -> Path:
    path = state_path_for_toplevel(toplevel=toplevel)
    write_state(
        path=path,
        state={
            "session_id": session_id,
            "branch": "develop",
            "worktree": "",
            "working_directory": toplevel,
            "timestamp": "2026-01-01T00:00:00Z",
            "modified_files": [],
            "staged_files": [],
            "recent_commits": ["abc1234 Test commit"],
            "has_plan": False,
        },
    )
    return path


@pytest.fixture
def toplevel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Isolate state + plan resolution under a temp claude-home and repo root."""
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: str(repo))
    return str(repo)


class TestBuildReloadContext:
    def test_empty_without_state_or_plan(self, toplevel: str) -> None:
        assert session.build_reload_context() == ""

    def test_includes_state_when_present(self, toplevel: str) -> None:
        _write_state(toplevel=toplevel, session_id="reload-test-session")

        context = session.build_reload_context()

        assert "Prior session state detected" in context
        assert "reload-test-session" in context

    def test_consumes_state_file_once(self, toplevel: str) -> None:
        path = _write_state(toplevel=toplevel, session_id="cleanup-test")
        assert path.exists()

        session.build_reload_context()

        assert not path.exists()
