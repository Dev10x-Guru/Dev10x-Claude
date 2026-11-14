"""GH-1568: SKILLS.md still lists every installed plugin's skills.

skill-index left core for dev10x-teach (ADR-0034 B5), so the generator now
runs from the satellite and must find core beside it. SessionStart only reads
``~/.claude/SKILLS.md``, so this runs the installed-layout generator against a
throwaway HOME and checks the index names every visible Dev10x skill.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from dev10x.core.paths import skill_files

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.999.0"
TIMEOUT_SECONDS = 120

pytestmark = pytest.mark.skipif(
    (shutil.which("yq") is None or shutil.which("jq") is None) and not os.environ.get("CI"),
    reason="yq or jq not installed",
)


def _install_core(*, publisher: Path) -> None:
    core = publisher / "dev10x" / VERSION
    shutil.copytree(REPO_ROOT / "skills", core / "skills")
    shutil.copytree(REPO_ROOT / "plugins", core / "plugins")
    shutil.copytree(REPO_ROOT / ".claude-plugin", core / ".claude-plugin")
    (core / "bin").mkdir()
    shutil.copy2(REPO_ROOT / "bin" / "require-tool.sh", core / "bin" / "require-tool.sh")
    plugin_map = core / "src" / "dev10x" / "core" / "plugins.yaml"
    plugin_map.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "src" / "dev10x" / "core" / "plugins.yaml", plugin_map)


def _install_teach(*, publisher: Path) -> Path:
    teach = publisher / "dev10x-teach" / VERSION
    shutil.copytree(REPO_ROOT / "plugins" / "teach", teach)
    return teach


@pytest.fixture(scope="module")
def skills_md(tmp_path_factory: pytest.TempPathFactory) -> str:
    home = tmp_path_factory.mktemp("home")
    publisher = home / ".claude" / "plugins" / "cache" / "Dev10x-Guru"
    _install_core(publisher=publisher)
    teach = _install_teach(publisher=publisher)
    env = {**os.environ, "HOME": str(home)}
    result = subprocess.run(
        [str(teach / "skills" / "skill-index" / "scripts" / "generate-all.sh"), "--force"],
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    return (home / ".claude" / "SKILLS.md").read_text()


def _front_matter(*, path: Path) -> dict:
    _, front, _ = path.read_text().split("---", 2)
    return yaml.safe_load(front)


def _hidden() -> set[str]:
    hidden = REPO_ROOT / "plugins" / "teach" / "skills" / "skill-index" / "hidden.yaml"
    return set(yaml.safe_load(hidden.read_text())["hidden"])


def _visible_skill_names() -> list[str]:
    hidden = _hidden()
    names = []
    for path in skill_files(repo_root=REPO_ROOT):
        meta = _front_matter(path=path)
        key = meta.get("invocation-name") or meta["name"]
        if key not in hidden and meta["name"] not in hidden:
            names.append(meta["name"])
    return sorted(names)


@pytest.mark.parametrize("name", _visible_skill_names())
def test_lists_every_visible_skill(skills_md: str, name: str) -> None:
    assert f"/{name}" in skills_md


@pytest.mark.parametrize(
    "plugin",
    ["dev10x:", "dev10x-teach:", "dev10x-comm:", "dev10x-qa:", "dev10x-db:", "dev10x-infra:"],
)
def test_names_skills_from_every_plugin(skills_md: str, plugin: str) -> None:
    assert f"/{plugin}" in skills_md
