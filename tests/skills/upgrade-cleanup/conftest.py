"""Fakes shared by the upgrade-cleanup tests (GH-1887)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from dev10x.core.plugin_map import PluginMap

PUBLISHER = "Dev10x-Guru"


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def make_plugin_map() -> Callable[..., PluginMap]:
    """Every key in ``plugins`` is extracted unless ``extracted`` says otherwise."""

    def build(
        *,
        plugins: Mapping[str, Sequence[str]],
        plugin_names: Mapping[str, str] | None = None,
        extracted: Sequence[str] | None = None,
    ) -> PluginMap:
        return PluginMap(
            plugins={key: tuple(skills) for key, skills in plugins.items()},
            plugin_names=dict(plugin_names or {}),
            marketplace=PUBLISHER,
            extracted=tuple(plugins if extracted is None else extracted),
        )

    return build


@pytest.fixture
def make_plugin_cache(fake_home: Path) -> Callable[..., Path]:
    """``<home>/.claude/plugins/cache/<publisher>/<plugin_name>/<version>``."""

    def build(
        *,
        plugin_name: str,
        version: str,
        publisher: str = PUBLISHER,
    ) -> Path:
        root = fake_home / ".claude" / "plugins" / "cache" / publisher / plugin_name / version
        root.mkdir(parents=True, exist_ok=True)
        return root

    return build


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps({"permissions": {"allow": []}}))
    return path


@pytest.fixture
def read_allow() -> Callable[[Path], list[str]]:
    def read(settings: Path) -> list[str]:
        return json.loads(settings.read_text())["permissions"]["allow"]

    return read
