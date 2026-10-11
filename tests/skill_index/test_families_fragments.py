"""GH-1552: the skill-index generators read families.yaml as plugin fragments.

The generators are shell, so the merge lives in lib-families.sh. These
tests pin it to the semantics dev10x.core.config.fragments implements,
so the two loaders cannot drift apart.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from dev10x.core.config.fragments import discover_fragments, load_merged, plugin_order
from dev10x.core.plugin_map import PLUGIN_MAP_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "skills" / "skill-index" / "scripts" / "lib-families.sh"
SHELL_TIMEOUT_SECONDS = 60

pytestmark = pytest.mark.skipif(shutil.which("yq") is None, reason="yq not installed")


def _shell(*, script: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}"; {script}', "lib", *args],
        capture_output=True,
        text=True,
        timeout=SHELL_TIMEOUT_SECONDS,
    )


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "skill-index"
    fragments = directory / "families.d"
    fragments.mkdir(parents=True)
    (directory / "families.yaml").write_text(
        yaml.safe_dump(
            {
                "display_map": {"logs": "logs:start"},
                "families": [{"label": "Pipeline", "skills": ["a"]}],
            }
        )
    )
    (fragments / "coding.yaml").write_text(
        yaml.safe_dump(
            {
                "display_map": {"commit": "dev10x:git-commit"},
                "families": [{"label": "Git", "skills": ["commit"]}],
            }
        )
    )
    (fragments / "tasks.yaml").write_text(
        yaml.safe_dump({"families": [{"label": "Session", "skills": ["dev10x:park"]}]})
    )
    return directory


@pytest.fixture
def shell_sources(skill_dir: Path) -> list[str]:
    result = _shell(
        script='families_sources "$1" "$2"',
        args=[str(skill_dir), str(PLUGIN_MAP_PATH)],
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


class TestFamiliesSources:
    def test_lists_the_base_then_fragments_in_plugin_order(
        self, skill_dir: Path, shell_sources: list[str]
    ) -> None:
        fragments = skill_dir / "families.d"
        assert shell_sources == [
            str(skill_dir / "families.yaml"),
            str(fragments / "tasks.yaml"),
            str(fragments / "coding.yaml"),
        ]

    def test_refuses_a_fragment_named_after_no_plugin(self, skill_dir: Path) -> None:
        (skill_dir / "families.d" / "stray.yaml").write_text("families: []\n")
        result = _shell(
            script='families_sources "$1" "$2"',
            args=[str(skill_dir), str(PLUGIN_MAP_PATH)],
        )
        assert result.returncode == 1
        assert "must be named after a plugin" in result.stderr

    def test_a_skill_dir_without_fragments_has_one_source(self, tmp_path: Path) -> None:
        (tmp_path / "families.yaml").write_text("families: []\n")
        result = _shell(
            script='families_sources "$1" "$2"',
            args=[str(tmp_path), str(PLUGIN_MAP_PATH)],
        )
        assert result.stdout.split() == [str(tmp_path / "families.yaml")]

    def test_plugin_order_matches_the_python_loader(self) -> None:
        result = _shell(script='plugin_order "$1"', args=[str(PLUGIN_MAP_PATH)])
        assert tuple(result.stdout.split()) == plugin_order()


class TestMergeFamilies:
    def test_shell_merge_equals_the_python_merge(
        self, skill_dir: Path, shell_sources: list[str], tmp_path: Path
    ) -> None:
        output = tmp_path / "merged.yaml"
        result = _shell(script='merge_families "$@"', args=[str(output), *shell_sources])
        assert result.returncode == 0, result.stderr

        fragments = discover_fragments(
            directories=[skill_dir / "families.d"], plugins=plugin_order()
        )
        base = yaml.safe_load((skill_dir / "families.yaml").read_text())
        expected = load_merged(fragments=fragments, base=("families.yaml", base))
        assert yaml.safe_load(output.read_text()) == expected


class TestPluginSkillDirs:
    def test_lists_the_dev10x_skills_then_stage_b_plugin_roots(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        qa = tmp_path / "plugins" / "qa" / "skills"
        skills.mkdir()
        qa.mkdir(parents=True)
        result = _shell(script='plugin_skill_dirs "$1"', args=[str(skills)])
        assert result.stdout.split() == [str(skills), str(qa)]

    def test_an_unresolved_dev10x_dir_lists_nothing(self) -> None:
        result = _shell(script='plugin_skill_dirs "$1"', args=[""])
        assert result.stdout == ""
