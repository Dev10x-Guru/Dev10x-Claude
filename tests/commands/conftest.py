"""Keep CLI command tests out of the developer's real ``~/.claude``.

The ``dev10x permission`` commands discover settings files through
``include_user_settings``, so a test whose discovery stub stops applying
after a refactor would otherwise read and write the real ``~/.claude``
settings (GH-1664). An isolated Claude home keeps that inside a sandbox.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir


@pytest.fixture(autouse=True)
def _isolate_claude_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(tmp_path / "claude-home"))
    ClaudeDir.reset_cache()


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "config"
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(home))
    Dev10xConfigDir.reset_cache()
    yield home
    Dev10xConfigDir.reset_cache()
