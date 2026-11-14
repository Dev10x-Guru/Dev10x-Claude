"""GH-1567: a bus script finds core's src/ in every dev10x-comm layout."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_SRC = REPO_ROOT / "plugins" / "comm" / "skills" / "bus" / "lib" / "core_src.py"
SCRIPT_PARTS = ("skills", "bus", "scripts", "send.py")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bus_core_src", CORE_SRC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core_src = _load()


def _script(*, plugin_root: Path) -> Path:
    script = plugin_root.joinpath(*SCRIPT_PARTS)
    script.parent.mkdir(parents=True)
    script.touch()
    return script


def _package(*, src: Path) -> Path:
    (src / "dev10x").mkdir(parents=True)
    return src


class TestFindCoreSrc:
    def test_pre_split_core_root(self, tmp_path: Path) -> None:
        src = _package(src=tmp_path / "src")

        assert core_src.find_core_src(script=_script(plugin_root=tmp_path)) == src

    def test_checkout_holds_the_satellite_under_plugins(self, tmp_path: Path) -> None:
        src = _package(src=tmp_path / "src")
        script = _script(plugin_root=tmp_path / "plugins" / "comm")

        assert core_src.find_core_src(script=script) == src

    def test_installed_satellite_reads_core_beside_it_at_its_newest_version(
        self,
        tmp_path: Path,
    ) -> None:
        publisher = tmp_path / "cache" / "Dev10x-Guru"
        _package(src=publisher / "dev10x" / "0.9.0" / "src")
        newest = _package(src=publisher / "dev10x" / "0.10.0" / "src")
        script = _script(plugin_root=publisher / "dev10x-comm" / "0.10.0")

        assert core_src.find_core_src(script=script) == newest

    def test_finds_nothing_without_core(self, tmp_path: Path) -> None:
        script = _script(plugin_root=tmp_path / "dev10x-comm" / "0.10.0")

        assert core_src.find_core_src(script=script) is None

    def test_repo_bus_script_resolves_to_the_repo_src(self) -> None:
        script = REPO_ROOT.joinpath("plugins", "comm", *SCRIPT_PARTS)

        assert core_src.find_core_src(script=script) == REPO_ROOT / "src"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("0.10.0", (0, 10, 0)), ("dev", (0,))],
)
def test_version_key(name: str, expected: tuple[int, ...]) -> None:
    assert core_src._version_key(name) == expected


class TestAddCoreSrc:
    @pytest.fixture
    def script(self, tmp_path: Path) -> Path:
        _package(src=tmp_path / "src")
        return _script(plugin_root=tmp_path)

    @pytest.fixture
    def clean_path(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        path = list(sys.path)
        monkeypatch.setattr(sys, "path", path)
        return path

    def test_inserts_core_src_once(
        self,
        script: Path,
        clean_path: list[str],
        tmp_path: Path,
    ) -> None:
        core_src.add_core_src(script=script)
        core_src.add_core_src(script=script)

        assert clean_path.count(str(tmp_path / "src")) == 1

    def test_leaves_the_path_alone_without_core(
        self,
        tmp_path: Path,
        clean_path: list[str],
    ) -> None:
        before = list(clean_path)

        core_src.add_core_src(script=_script(plugin_root=tmp_path / "x" / "y"))

        assert clean_path == before
