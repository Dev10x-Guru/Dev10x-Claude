"""GH-1568: a skill-audit script finds core's src/ in every dev10x-teach layout."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEACH_CORE_SRC = REPO_ROOT / "plugins" / "teach" / "skills" / "skill-audit" / "lib" / "core_src.py"
COMM_CORE_SRC = REPO_ROOT / "plugins" / "comm" / "skills" / "bus" / "lib" / "core_src.py"
SCRIPT_PARTS = ("skills", "skill-audit", "scripts", "extract-session.py")
SHIMS = ("extract-session.py", "analyze-actions.py", "analyze-permissions.py")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("teach_core_src", TEACH_CORE_SRC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core_src = _load()


def _code_without_docstring(*, path: Path) -> str:
    tree = ast.parse(path.read_text())
    tree.body = tree.body[1:]
    return ast.unparse(tree)


def _script(*, plugin_root: Path) -> Path:
    script = plugin_root.joinpath(*SCRIPT_PARTS)
    script.parent.mkdir(parents=True)
    script.touch()
    return script


def _package(*, src: Path) -> Path:
    (src / "dev10x").mkdir(parents=True)
    return src


def test_mirrors_the_comm_copy() -> None:
    assert _code_without_docstring(path=TEACH_CORE_SRC) == _code_without_docstring(
        path=COMM_CORE_SRC
    )


class TestFindCoreSrc:
    @pytest.mark.parametrize("shim", SHIMS)
    def test_repo_script_resolves_to_the_repo_src(self, shim: str) -> None:
        script = REPO_ROOT / "plugins" / "teach" / "skills" / "skill-audit" / "scripts" / shim

        assert core_src.find_core_src(script=script) == REPO_ROOT / "src"

    def test_installed_satellite_reads_core_beside_it_at_its_newest_version(
        self,
        tmp_path: Path,
    ) -> None:
        publisher = tmp_path / "cache" / "Dev10x-Guru"
        _package(src=publisher / "dev10x" / "0.9.0" / "src")
        newest = _package(src=publisher / "dev10x" / "0.10.0" / "src")
        script = _script(plugin_root=publisher / "dev10x-teach" / "0.10.0")

        assert core_src.find_core_src(script=script) == newest

    def test_finds_nothing_without_core(self, tmp_path: Path) -> None:
        script = _script(plugin_root=tmp_path / "dev10x-teach" / "0.10.0")

        assert core_src.find_core_src(script=script) is None
