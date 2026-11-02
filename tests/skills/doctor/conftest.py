"""Shared fixtures for plugin-doctor strategy tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

type WriteSettings = Callable[..., Path]


@pytest.fixture
def write_settings() -> WriteSettings:
    """Write a checkout's ``.claude/settings.local.json`` with the given allows."""

    def _write(*, checkout: Path, allow: list[str]) -> Path:
        path = checkout / ".claude" / "settings.local.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"permissions": {"allow": allow}}))
        return path

    return _write
