"""Tests for the shared gh JSON helper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dev10x.skills.notifications import _gh


def test_raises_gh_command_error_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _gh.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    with pytest.raises(_gh.GhCommandError, match="boom"):
        _gh.gh_json(args=["pr", "view", "1"])


def test_returns_parsed_json_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _gh.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr=""),
    )
    assert _gh.gh_json(args=["pr", "view", "1"]) == {"ok": True}
