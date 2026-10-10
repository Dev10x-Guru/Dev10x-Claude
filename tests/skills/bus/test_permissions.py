"""The bus scripts get allow rules without a hand-added settings entry (GH-1516)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dev10x.skills.permission.catalog_rules import scan_plugin_scripts

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
BUS_SCRIPTS = [
    PLUGIN_ROOT / "skills" / "bus" / "scripts" / name
    for name in ("send.py", "watch.py", "done.py")
]


@pytest.fixture(scope="module")
def scanned() -> list[Path]:
    return scan_plugin_scripts(plugin_root=PLUGIN_ROOT)


@pytest.mark.parametrize("script", BUS_SCRIPTS, ids=lambda path: path.name)
def test_ensure_scripts_scan_includes_bus_script(scanned: list[Path], script: Path) -> None:
    assert script in scanned


@pytest.mark.parametrize("script", BUS_SCRIPTS, ids=lambda path: path.name)
def test_bus_script_is_executable(script: Path) -> None:
    assert os.access(script, os.X_OK)
