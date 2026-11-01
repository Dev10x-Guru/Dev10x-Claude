from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dev10x.core.domain.plugin_identity import CORE_PLUGIN_NAMES, PLUGIN_NAMES
from dev10x.core.skills.permission.catalog_version import update_file
from dev10x.core.skills.permission.clean_project_files import is_old_version

CACHE = "~/.claude/plugins/cache/Dev10x-Guru"


@pytest.mark.parametrize(
    ("fragment", "slug", "expected"),
    [
        pytest.param(PLUGIN_NAMES, "dev10x", True, id="any-core"),
        pytest.param(PLUGIN_NAMES, "Dev10x", True, id="any-legacy-title-case"),
        pytest.param(PLUGIN_NAMES, "dev10x-claude", True, id="any-legacy-repo-slug"),
        pytest.param(PLUGIN_NAMES, "dev10x-qa", True, id="any-satellite"),
        pytest.param(PLUGIN_NAMES, "superpowers", False, id="any-other-plugin"),
        pytest.param(PLUGIN_NAMES, "dev10x-", False, id="any-empty-area"),
        pytest.param(CORE_PLUGIN_NAMES, "dev10x-claude", True, id="core-legacy-repo-slug"),
        pytest.param(CORE_PLUGIN_NAMES, "dev10x-qa", False, id="core-not-satellite"),
    ],
)
def test_plugin_name_fragments(fragment: str, slug: str, expected: bool) -> None:
    assert bool(re.fullmatch(fragment, slug)) is expected


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        f"Bash({CACHE}/dev10x-qa/0.111.0/skills/tts/scripts/x.py:*)",
                        f"Bash({CACHE}/Dev10x/0.105.0/skills/git/scripts/y.sh:*)",
                    ]
                }
            }
        )
    )
    return path


@pytest.fixture
def rewritten(settings: Path) -> list[str]:
    update_file(settings, "0.112.0", target_plugin_dir="dev10x")
    return json.loads(settings.read_text())["permissions"]["allow"]


class TestUpdatePaths:
    def test_a_satellite_rule_keeps_its_directory(self, rewritten: list[str]) -> None:
        assert rewritten[0] == f"Bash({CACHE}/dev10x-qa/0.112.0/skills/tts/scripts/x.py:*)"

    def test_a_legacy_core_rule_moves_to_the_core_directory(self, rewritten: list[str]) -> None:
        assert rewritten[1] == f"Bash({CACHE}/dev10x/0.112.0/skills/git/scripts/y.sh:*)"


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        pytest.param(f"Bash({CACHE}/dev10x/0.111.0/skills/git/x:*)", True, id="old-core"),
        pytest.param(f"Bash({CACHE}/dev10x-qa/0.111.0/skills/tts/x:*)", False, id="satellite"),
    ],
)
def test_clean_prunes_only_old_core_rules(rule: str, expected: bool) -> None:
    assert is_old_version(rule, "0.112.0") is expected
