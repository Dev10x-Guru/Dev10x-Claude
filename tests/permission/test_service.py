"""Tests for the permission service layer (GH-584, audit N18).

The service owns the `find_config` → `load_config` →
`find_settings_files` sequence shared by the MCP adapter and the CLI,
so neither inlines the boilerplate nor reaches into
`skills.permission` directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.common.result import ErrorResult, err, ok
from dev10x.permission import service
from dev10x.skills.permission import update_paths as up


@pytest.fixture
def stub_config(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stub find_config/load_config; record find_settings_files args."""
    captured: dict = {}
    monkeypatch.setattr(up, "find_config", lambda: ok(Path("/cfg.yaml")))
    monkeypatch.setattr(
        up,
        "load_config",
        lambda _path: {"roots": ["/root"], "include_user_settings": True},
    )

    def fake_find_settings_files(*, roots: list[str], include_user: bool) -> list[Path]:
        captured["roots"] = roots
        captured["include_user"] = include_user
        return [Path("/proj/.claude/settings.local.json")]

    monkeypatch.setattr(up, "find_settings_files", fake_find_settings_files)
    return captured


def test_returns_context_on_success(stub_config: dict) -> None:
    result = service.load_permission_context()
    assert not isinstance(result, ErrorResult)
    ctx = result.value
    assert ctx.config_path == Path("/cfg.yaml")
    assert ctx.config["roots"] == ["/root"]
    assert ctx.settings_files == [Path("/proj/.claude/settings.local.json")]


def test_honors_config_include_user_by_default(stub_config: dict) -> None:
    service.load_permission_context()
    assert stub_config["include_user"] is True


def test_explicit_include_user_overrides_config(stub_config: dict) -> None:
    service.load_permission_context(include_user=False)
    assert stub_config["include_user"] is False


def test_passes_through_find_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up, "find_config", lambda: err("no config"))
    result = service.load_permission_context()
    assert isinstance(result, ErrorResult)
    assert result.error == "no config"


def test_empty_settings_files_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(up, "find_config", lambda: ok(Path("/cfg.yaml")))
    monkeypatch.setattr(up, "load_config", lambda _path: {"roots": []})
    monkeypatch.setattr(up, "find_settings_files", lambda *, roots, include_user: [])
    result = service.load_permission_context()
    assert not isinstance(result, ErrorResult)
    assert result.value.settings_files == []
