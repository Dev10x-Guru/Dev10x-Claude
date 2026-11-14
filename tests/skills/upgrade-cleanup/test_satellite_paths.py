"""Rules for extracted skills follow them into their satellite (GH-1793)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from dev10x.skills.permission.satellite_paths import (
    RuleMove,
    SatelliteRelocator,
    relocate_file,
    relocate_rule,
)

from dev10x.core.plugin_map import PluginMap, load_plugin_map

CACHE = "~/.claude/plugins/cache/Dev10x-Guru"
MARKET = "~/.claude/plugins/marketplaces/Dev10x-Guru"

CORE_AWS = f"Bash({CACHE}/dev10x/0.114.0/skills/aws-vault/scripts/aws.sh:*)"
INFRA_AWS = f"Bash({CACHE}/dev10x-infra/0.114.0/skills/aws-vault/scripts/aws.sh:*)"
MARKET_AWS = f"Bash({MARKET}/skills/aws-vault/scripts/aws.sh:*)"
MARKET_INFRA_AWS = f"Bash({MARKET}/plugins/infra/skills/aws-vault/scripts/aws.sh:*)"
CORE_GIT = f"Bash({CACHE}/dev10x/0.114.0/skills/git/scripts/git.sh:*)"
CORE_K8S = f"Bash({CACHE}/Dev10x/0.113.0/skills/k8s/scripts/k8s.sh:*)"
INFRA_K8S = f"Bash({CACHE}/dev10x-infra/0.113.0/skills/k8s/scripts/k8s.sh:*)"


@pytest.fixture
def plugin_map(make_plugin_map: Callable[..., PluginMap]) -> PluginMap:
    return make_plugin_map(
        plugins={"infra": ["aws-vault", "k8s"], "db": ["db"], "core": ["git"]},
        plugin_names={"infra": "dev10x-infra", "db": "dev10x-db", "core": "dev10x"},
        extracted=["infra"],
    )


@pytest.fixture
def relocator(plugin_map: PluginMap) -> SatelliteRelocator:
    return SatelliteRelocator(plugin_map=plugin_map)


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": [CORE_AWS, INFRA_AWS, MARKET_AWS, CORE_GIT],
                    "deny": [CORE_K8S],
                },
                "model": "opus",
            }
        )
    )
    return path


@pytest.fixture
def relocated(settings_file: Path, relocator: SatelliteRelocator) -> tuple[int, list[str]]:
    return relocate_file(settings_file, relocator=relocator)


def _data(path: Path) -> dict:
    return json.loads(path.read_text())


class TestMovedSkills:
    def test_lists_only_extracted_keys(self, relocator: SatelliteRelocator) -> None:
        assert relocator.moved_skills == {"aws-vault": "infra", "k8s": "infra"}

    def test_shipped_map_covers_both_extractions(self) -> None:
        moved = SatelliteRelocator(plugin_map=load_plugin_map()).moved_skills

        assert (moved["qa-self"], moved["aws-vault"]) == ("qa", "infra")


class TestRelocateRule:
    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            (CORE_AWS, INFRA_AWS),
            (MARKET_AWS, MARKET_INFRA_AWS),
            (CORE_K8S, INFRA_K8S),
            (
                "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/dev10x-claude/0.1.0/skills/k8s/x:*)",
                "Bash(/home/u/.claude/plugins/cache/Dev10x-Guru/dev10x-infra/0.1.0/skills/k8s/x:*)",
            ),
        ],
    )
    def test_moves_an_extracted_skill(
        self,
        plugin_map: PluginMap,
        rule: str,
        expected: str,
    ) -> None:
        assert relocate_rule(rule=rule, plugin_map=plugin_map) == expected

    @pytest.mark.parametrize(
        "rule",
        [
            CORE_GIT,
            f"Bash({MARKET}/skills/git/scripts/git.sh:*)",
            "Bash(~/.claude/plugins/marketplaces/other-pub/skills/k8s/scripts/k8s.sh:*)",
            INFRA_AWS,
            MARKET_INFRA_AWS,
            f"Bash({CACHE}/dev10x/0.114.0/skills/db/scripts/db.sh:*)",
            f"Read({CACHE}/dev10x/0.114.0/**)",
            f"Bash({CACHE}/dev10x/0.114.0/skills/aws-vault-extra/x.sh:*)",
            "mcp__plugin_dev10x_cli__mktmp",
        ],
    )
    def test_leaves_other_rules_alone(self, plugin_map: PluginMap, rule: str) -> None:
        assert relocate_rule(rule=rule, plugin_map=plugin_map) == rule

    def test_falls_back_to_the_expected_plugin_name(
        self,
        make_plugin_map: Callable[..., PluginMap],
    ) -> None:
        unnamed = make_plugin_map(plugins={"infra": ["k8s"]})

        assert relocate_rule(rule=CORE_K8S, plugin_map=unnamed) == INFRA_K8S


class TestRelocatePermissions:
    @pytest.mark.parametrize(
        ("permissions", "expected_lists", "expected_moves"),
        [
            (
                {"allow": [CORE_AWS, INFRA_AWS]},
                {"allow": [INFRA_AWS]},
                [RuleMove(rule_list="allow", old=CORE_AWS, new=INFRA_AWS, kept=False)],
            ),
            (
                {"deny": [CORE_K8S]},
                {"deny": [CORE_K8S, INFRA_K8S]},
                [RuleMove(rule_list="deny", old=CORE_K8S, new=INFRA_K8S, kept=True)],
            ),
            ({"ask": [CORE_K8S, INFRA_K8S]}, {"ask": [CORE_K8S, INFRA_K8S]}, []),
            (
                {"allow": [CORE_GIT, CORE_GIT, CORE_AWS]},
                {"allow": [CORE_GIT, CORE_GIT, INFRA_AWS]},
                [RuleMove(rule_list="allow", old=CORE_AWS, new=INFRA_AWS, kept=False)],
            ),
            (
                {"allow": [7, {"x": 1}, CORE_GIT], "deny": "oops"},
                {"allow": [7, {"x": 1}, CORE_GIT]},
                [],
            ),
        ],
        ids=[
            "allow-replaced",
            "deny-kept",
            "kept-already-relocated",
            "user-duplicates-untouched",
            "odd-entries",
        ],
    )
    def test_rewrites_each_list(
        self,
        relocator: SatelliteRelocator,
        permissions: dict,
        expected_lists: dict,
        expected_moves: list[RuleMove],
    ) -> None:
        assert relocator.relocate_permissions(permissions=permissions) == (
            expected_lists,
            expected_moves,
        )


class TestRuleMove:
    @pytest.mark.parametrize(
        ("rule_list", "kept", "expected"),
        [
            ("allow", False, "  [allow] a → b"),
            ("deny", True, "  [deny] a → b (original kept)"),
        ],
    )
    def test_describes_the_move(self, rule_list: str, kept: bool, expected: str) -> None:
        move = RuleMove(rule_list=rule_list, old="a", new="b", kept=kept)

        assert move.describe() == expected


class TestRelocateFile:
    def test_reports_every_move(self, relocated: tuple[int, list[str]]) -> None:
        assert relocated == (
            3,
            [
                f"  [allow] {CORE_AWS} → {INFRA_AWS}",
                f"  [allow] {MARKET_AWS} → {MARKET_INFRA_AWS}",
                f"  [deny] {CORE_K8S} → {INFRA_K8S} (original kept)",
            ],
        )

    @pytest.mark.usefixtures("relocated")
    def test_rewrites_the_lists_and_keeps_other_keys(self, settings_file: Path) -> None:
        assert _data(settings_file) == {
            "permissions": {
                "allow": [INFRA_AWS, MARKET_INFRA_AWS, CORE_GIT],
                "deny": [CORE_K8S, INFRA_K8S],
            },
            "model": "opus",
        }

    @pytest.mark.usefixtures("relocated")
    def test_second_run_is_a_no_op(
        self,
        settings_file: Path,
        relocator: SatelliteRelocator,
    ) -> None:
        assert relocate_file(settings_file, relocator=relocator) == (0, [])

    def test_dry_run_leaves_the_file_alone(
        self,
        settings_file: Path,
        relocator: SatelliteRelocator,
    ) -> None:
        before = settings_file.read_text()

        relocate_file(settings_file, relocator=relocator, dry_run=True)

        assert settings_file.read_text() == before

    @pytest.mark.parametrize(
        ("content", "expected_prefix"),
        [
            ("{not json", "  SKIP (invalid JSON)"),
            ("[]", "  SKIP (unexpected structure)"),
            ("null", "  SKIP (unexpected structure)"),
            ('{"permissions": "x"}', "  SKIP (unexpected structure)"),
        ],
    )
    def test_skips_a_file_it_cannot_use(
        self,
        tmp_path: Path,
        relocator: SatelliteRelocator,
        content: str,
        expected_prefix: str,
    ) -> None:
        path = tmp_path / "settings.json"
        path.write_text(content)

        count, messages = relocate_file(path, relocator=relocator)

        assert count == 0
        assert len(messages) == 1
        assert messages[0].startswith(expected_prefix)

    def test_skips_a_missing_file(self, tmp_path: Path, relocator: SatelliteRelocator) -> None:
        count, messages = relocate_file(tmp_path / "absent.json", relocator=relocator)

        assert count == 0
        assert messages[0].startswith("  SKIP (unreadable)")

    def test_defaults_to_the_shipped_plugin_map(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": [CORE_AWS]}}))

        assert relocate_file(path, dry_run=True) == (
            1,
            [f"  [allow] {CORE_AWS} → {INFRA_AWS}"],
        )
