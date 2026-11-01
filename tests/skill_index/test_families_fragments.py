"""GH-1552: the skill-index generators read families.yaml as plugin fragments.

The generators are shell, so the merge lives in lib-families.sh. These
tests pin it to the semantics dev10x.core.config.fragments implements,
so the two loaders cannot drift apart.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from dev10x.core.config.fragments import discover_fragments, load_merged, plugin_order
from dev10x.core.plugin_map import PLUGIN_MAP_PATH, load_plugin_map

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "skills" / "skill-index" / "scripts" / "lib-families.sh"
SHELL_TIMEOUT_SECONDS = 60

pytestmark = pytest.mark.skipif(
    shutil.which("yq") is None and not os.environ.get("CI"),
    reason="yq not installed",
)


def _shell(*, script: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}"; {script}', "lib", *args],
        capture_output=True,
        text=True,
        timeout=SHELL_TIMEOUT_SECONDS,
    )


def _shell_stdout(*, script: str, args: list[str]) -> str:
    result = _shell(script=script, args=args)
    assert result.returncode == 0, result.stderr
    return result.stdout


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
        stdout = _shell_stdout(
            script='families_sources "$1" "$2"',
            args=[str(tmp_path), str(PLUGIN_MAP_PATH)],
        )
        assert stdout.split() == [str(tmp_path / "families.yaml")]

    def test_plugin_order_matches_the_python_loader(self) -> None:
        stdout = _shell_stdout(script='plugin_order "$1"', args=[str(PLUGIN_MAP_PATH)])
        assert tuple(stdout.split()) == plugin_order()


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


SHIPPED_SKILL_DIR = REPO_ROOT / "skills" / "skill-index"

#: The pre-split display_map minus the entries that named no Dev10x skill
#: (`logs`, `triage-sentry`, `app-db`) and the inverted
#: `dev10x:investigate: investigate`, which resolved to no key (GH-1589).
EXPECTED_DISPLAY_MAP = {
    "commit": "dev10x:git-commit",
    "commit:split": "dev10x:git-commit-split",
    "commit:fixup": "dev10x:git-fixup",
    "commit:to-new-ticket": "dev10x:git-promote",
    "branch:groom": "dev10x:git-groom",
    "pr:create": "dev10x:gh-pr-create",
    "pr:respond": "dev10x:gh-pr-respond",
    "pr:monitor": "dev10x:gh-pr-monitor",
    "pr:request-review": "dev10x:gh-pr-request-review",
    "pr:triage": "dev10x:gh-pr-triage",
    "pr:comment-fixup": "dev10x:gh-pr-fixup",
    "ticket:work-on": "dev10x:work-on",
    "release-notes": "dev10x:release-notes",
}

#: Family order in SKILLS.md: core first, then plugins.yaml order.
EXPECTED_FAMILIES = {
    "Setup": "core",
    "QA": "qa",
    "Data": "db",
    "Meta": "teach",
    "Session": "tasks",
    "Scoping": "scoping",
    "Diagrams": "scoping",
    "Pipeline": "coding",
    "Git": "coding",
    "PR": "coding",
    "Testing": "coding",
    "Ops": "coding",
    "Reports": "coding",
}

DEV10X_PLUGIN_NAMES = frozenset(load_plugin_map().known_plugin_names())


def _shipped_family_files() -> list[tuple[str, Path]]:
    fragments = discover_fragments(
        directories=[SHIPPED_SKILL_DIR / "families.d"], plugins=plugin_order()
    )
    return [("core", SHIPPED_SKILL_DIR / "families.yaml")] + [
        (fragment.plugin, fragment.path) for fragment in fragments
    ]


def _skill_directory(*, name: str) -> str:
    # A name outside every Dev10x plugin keeps its full spelling, which
    # names no skill directory, so the ownership test below reports it.
    plugin, _, skill = name.partition(":")
    return skill if plugin in DEV10X_PLUGIN_NAMES else name


def _family_members() -> list[tuple[str, str, str]]:
    """(fragment plugin, family label, skill directory) for every entry."""
    display_map: dict[str, str] = {}
    documents = [
        (plugin, yaml.safe_load(path.read_text())) for plugin, path in _shipped_family_files()
    ]
    for _plugin, document in documents:
        display_map.update(document.get("display_map") or {})
    return [
        (plugin, family["label"], _skill_directory(name=display_map.get(entry, entry)))
        for plugin, document in documents
        for family in document.get("families") or []
        for entry in family["skills"]
    ]


class TestShippedFamilies:
    @pytest.fixture
    def merged(self, tmp_path: Path) -> dict:
        sources = _shell_stdout(
            script='families_sources "$1" "$2"',
            args=[str(SHIPPED_SKILL_DIR), str(PLUGIN_MAP_PATH)],
        ).split()
        output = tmp_path / "merged.yaml"
        _shell_stdout(script='merge_families "$@"', args=[str(output), *sources])
        return yaml.safe_load(output.read_text())

    def test_display_map_is_pinned(self, merged: dict) -> None:
        assert merged["display_map"] == EXPECTED_DISPLAY_MAP

    def test_families_merge_in_plugin_order(self, merged: dict) -> None:
        assert [family["label"] for family in merged["families"]] == list(EXPECTED_FAMILIES)

    def test_every_family_lives_whole_in_one_fragment(self) -> None:
        owners = {
            family["label"]: plugin
            for plugin, path in _shipped_family_files()
            for family in yaml.safe_load(path.read_text()).get("families") or []
        }
        assert owners == EXPECTED_FAMILIES

    @pytest.mark.parametrize(("plugin", "label", "skill"), _family_members())
    def test_every_skill_belongs_to_its_fragments_plugin(
        self, plugin: str, label: str, skill: str
    ) -> None:
        assert load_plugin_map().plugin_for(skill=skill) == plugin, label

    def test_no_display_name_maps_twice(self, merged: dict) -> None:
        values = list(merged["display_map"].values())
        assert len(values) == len(set(values))


class TestPluginSkillDirs:
    def test_lists_the_dev10x_skills_then_stage_b_plugin_roots(self, tmp_path: Path) -> None:
        skills = tmp_path / "skills"
        qa = tmp_path / "plugins" / "qa" / "skills"
        skills.mkdir()
        qa.mkdir(parents=True)
        stdout = _shell_stdout(script='plugin_skill_dirs "$1"', args=[str(skills)])
        assert stdout.split() == [str(skills), str(qa)]

    def test_an_unresolved_dev10x_dir_lists_nothing(self) -> None:
        stdout = _shell_stdout(script='plugin_skill_dirs "$1"', args=[""])
        assert stdout == ""
