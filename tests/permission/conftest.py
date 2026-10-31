"""Keep permission-adapter tests out of the developer's real ``~/.claude``.

These tests drive the MCP adapter end to end with the discovery seam
stubbed. When a refactor moves the seam, a stub that no longer applies
falls through to real discovery, and ``include_user_settings`` then
points ``ensure-base`` at the real ``~/.claude`` settings files — which
is how one GH-1664 iteration wrote three catalog rules into them. An
isolated Claude home turns that class of mistake into a failing test
inside a sandbox instead of a write to the developer's machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.domain.claude_paths import ClaudeDir


@pytest.fixture(autouse=True)
def _isolate_claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
    ClaudeDir.reset_cache()
