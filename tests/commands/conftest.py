"""Keep CLI command tests out of the developer's real ``~/.claude``.

The ``dev10x permission`` commands discover settings files through
``include_user_settings``, so a test whose discovery stub stops applying
after a refactor would otherwise read and write the real ``~/.claude``
settings (GH-1664). An isolated Claude home keeps that inside a sandbox.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.domain.claude_paths import ClaudeDir


@pytest.fixture(autouse=True)
def _isolate_claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
    ClaudeDir.reset_cache()
