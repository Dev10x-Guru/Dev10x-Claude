"""GH-1572: a coding uv-script shim finds core's src/ in every dev10x-coding layout."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CODING_SKILLS = REPO_ROOT / "plugins" / "coding" / "skills"
CODING_CORE_SRC = CODING_SKILLS / "git" / "lib" / "core_src.py"
COMM_CORE_SRC = REPO_ROOT / "plugins" / "comm" / "skills" / "bus" / "lib" / "core_src.py"
SHIMS = (
    "gh-pr-monitor/scripts/ci-check-status.py",
    "gh-pr-monitor/scripts/pr-notify.py",
    "release-notes/scripts/collect-prs.py",
    "git-fixup/scripts/find-fixup-target.py",
    "gh-pr-merge/scripts/reconcile-fixes-links.py",
    "gh-pr-merge/scripts/audit-handoff-report.py",
    "slack-review-request/scripts/slack-review-request.py",
)
IMPORT_TIMEOUT_SECONDS = 60


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coding_core_src", CODING_CORE_SRC)
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
    script = plugin_root / "skills" / "git-fixup" / "scripts" / "find-fixup-target.py"
    script.parent.mkdir(parents=True)
    script.touch()
    return script


def _package(*, src: Path) -> Path:
    (src / "dev10x").mkdir(parents=True)
    return src


def test_mirrors_the_comm_copy() -> None:
    assert _code_without_docstring(path=CODING_CORE_SRC) == _code_without_docstring(
        path=COMM_CORE_SRC
    )


class TestFindCoreSrc:
    @pytest.mark.parametrize("shim", SHIMS)
    def test_repo_script_resolves_to_the_repo_src(self, shim: str) -> None:
        assert core_src.find_core_src(script=CODING_SKILLS / shim) == REPO_ROOT / "src"

    def test_installed_satellite_reads_core_beside_it_at_its_newest_version(
        self,
        tmp_path: Path,
    ) -> None:
        publisher = tmp_path / "cache" / "Dev10x-Guru"
        _package(src=publisher / "dev10x" / "0.9.0" / "src")
        newest = _package(src=publisher / "dev10x" / "0.10.0" / "src")
        script = _script(plugin_root=publisher / "dev10x-coding" / "0.10.0")

        assert core_src.find_core_src(script=script) == newest

    def test_finds_nothing_without_core(self, tmp_path: Path) -> None:
        script = _script(plugin_root=tmp_path / "dev10x-coding" / "0.10.0")

        assert core_src.find_core_src(script=script) is None


@pytest.mark.parametrize("shim", SHIMS)
def test_every_shim_routes_through_core_src(shim: str) -> None:
    text = (CODING_SKILLS / shim).read_text()

    assert "add_core_src(script=Path(__file__))" in text
    assert 'parents[3] / "src"' not in text


def test_a_shim_imports_core_from_the_checkout() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(CODING_SKILLS / "git-fixup/scripts/find-fixup-target.py"),
            "-h",
        ],
        capture_output=True,
        text=True,
        timeout=IMPORT_TIMEOUT_SECONDS,
        check=False,
    )

    assert "ModuleNotFoundError" not in completed.stderr
