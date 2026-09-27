"""GH-1501: carry pre-rename ``Dev10x`` rule spellings to ``dev10x``."""

from __future__ import annotations

import pytest

from dev10x.skills.permission.legacy_namespace import (
    CURRENT_PLUGIN_ID,
    LEGACY_PLUGIN_ID,
    current_spelling,
    migrate_legacy_namespace,
)


class TestCurrentSpelling:
    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            ("Skill(Dev10x:git-commit)", "Skill(dev10x:git-commit)"),
            ("Skill(Dev10x:*)", "Skill(dev10x:*)"),
            ("mcp__plugin_Dev10x_cli__merge_pr", "mcp__plugin_dev10x_cli__merge_pr"),
            ("mcp__plugin_Dev10x_cli__*", "mcp__plugin_dev10x_cli__*"),
        ],
    )
    def test_legacy_rules_get_the_new_spelling(self, rule: str, expected: str) -> None:
        assert current_spelling(rule) == expected

    @pytest.mark.parametrize(
        "rule",
        [
            "Skill(dev10x:git-commit)",
            "mcp__plugin_dev10x_cli__merge_pr",
            "Read(~/.claude/skills/Dev10x:upgrade-cleanup/**)",
            "Bash(~/.claude/skills/Dev10x:upgrade-cleanup/scripts/x.sh:*)",
            "Read(~/.config/Dev10x/**)",
            "Edit(/tmp/Dev10x/git/**)",
            "Read(.claude/Dev10x/**)",
        ],
    )
    def test_everything_else_is_left_alone(self, rule: str) -> None:
        assert current_spelling(rule) is None


class TestMigrateRules:
    def test_deny_is_rewritten_in_place(self) -> None:
        data = {"permissions": {"deny": ["Bash(sudo:*)", "mcp__plugin_Dev10x_cli__merge_pr"]}}

        migrated, _ = migrate_legacy_namespace(data)

        assert migrated["permissions"]["deny"] == [
            "Bash(sudo:*)",
            "mcp__plugin_dev10x_cli__merge_pr",
        ]

    @pytest.mark.parametrize("list_name", ["deny", "ask", "allow"])
    def test_every_rule_list_is_migrated(self, list_name: str) -> None:
        data = {"permissions": {list_name: ["Skill(Dev10x:git)"]}}

        migrated, migration = migrate_legacy_namespace(data)

        assert migrated["permissions"][list_name] == ["Skill(dev10x:git)"]
        assert migration.rule_moves[0].list_name == list_name

    def test_a_deny_never_shrinks_the_list(self) -> None:
        denies = ["mcp__plugin_Dev10x_cli__merge_pr", "Skill(Dev10x:gh-pr-merge)"]

        migrated, _ = migrate_legacy_namespace({"permissions": {"deny": denies}})

        assert len(migrated["permissions"]["deny"]) == len(denies)

    def test_legacy_copy_of_a_present_rule_is_pruned(self) -> None:
        data = {"permissions": {"allow": ["Skill(Dev10x:*)", "Skill(dev10x:*)"]}}

        migrated, migration = migrate_legacy_namespace(data)

        assert migrated["permissions"]["allow"] == ["Skill(dev10x:*)"]
        assert migration.rule_moves[0].pruned is True

    def test_two_legacy_spellings_of_one_rule_collapse(self) -> None:
        data = {"permissions": {"deny": ["Skill(Dev10x:x)", "Skill(Dev10x:x)"]}}

        migrated, _ = migrate_legacy_namespace(data)

        assert migrated["permissions"]["deny"] == ["Skill(dev10x:x)"]

    def test_input_is_not_mutated(self) -> None:
        data = {"permissions": {"allow": ["Skill(Dev10x:git)"]}}

        migrate_legacy_namespace(data)

        assert data == {"permissions": {"allow": ["Skill(Dev10x:git)"]}}

    def test_non_string_entries_pass_through(self) -> None:
        data = {"permissions": {"allow": [42, "Skill(Dev10x:git)"]}}

        migrated, _ = migrate_legacy_namespace(data)

        assert migrated["permissions"]["allow"] == [42, "Skill(dev10x:git)"]

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"permissions": "nope"},
            {"permissions": {"allow": "nope"}},
            {"enabledPlugins": ["nope"]},
        ],
    )
    def test_malformed_shapes_are_left_alone(self, data: dict) -> None:
        migrated, migration = migrate_legacy_namespace(data)

        assert migrated == data
        assert migration.changed is False


class TestMigratePluginId:
    def test_legacy_id_is_renamed_keeping_its_value(self) -> None:
        data = {"enabledPlugins": {"a@b": True, LEGACY_PLUGIN_ID: False}}

        migrated, migration = migrate_legacy_namespace(data)

        assert migrated["enabledPlugins"] == {"a@b": True, CURRENT_PLUGIN_ID: False}
        assert migration.plugin_id_move is not None
        assert migration.plugin_id_move.pruned is False

    def test_legacy_id_beside_the_new_one_is_pruned(self) -> None:
        data = {"enabledPlugins": {LEGACY_PLUGIN_ID: True, CURRENT_PLUGIN_ID: False}}

        migrated, migration = migrate_legacy_namespace(data)

        assert migrated["enabledPlugins"] == {CURRENT_PLUGIN_ID: False}
        assert migration.plugin_id_move is not None
        assert migration.plugin_id_move.pruned is True


class TestIdempotence:
    def test_a_second_pass_is_a_no_op(self) -> None:
        data = {
            "permissions": {
                "allow": ["Skill(Dev10x:*)", "Skill(dev10x:*)", "mcp__plugin_Dev10x_cli__*"],
                "deny": ["mcp__plugin_Dev10x_cli__merge_pr"],
                "ask": ["Skill(Dev10x:gh-pr-merge)"],
            },
            "enabledPlugins": {LEGACY_PLUGIN_ID: True},
        }
        once, _ = migrate_legacy_namespace(data)

        twice, migration = migrate_legacy_namespace(once)

        assert twice == once
        assert migration.changed is False


class TestDescribe:
    def test_names_every_move(self) -> None:
        data = {
            "permissions": {
                "deny": ["mcp__plugin_Dev10x_cli__merge_pr"],
                "allow": ["Skill(Dev10x:*)", "Skill(dev10x:*)"],
            },
            "enabledPlugins": {LEGACY_PLUGIN_ID: True, CURRENT_PLUGIN_ID: True},
        }

        _, migration = migrate_legacy_namespace(data)

        assert migration.count == 3
        assert migration.describe() == [
            "deny: mcp__plugin_Dev10x_cli__merge_pr -> mcp__plugin_dev10x_cli__merge_pr",
            "allow: pruned Skill(Dev10x:*) (Skill(dev10x:*) already present)",
            f"enabledPlugins: pruned {LEGACY_PLUGIN_ID} ({CURRENT_PLUGIN_ID} already present)",
        ]

    def test_a_renamed_plugin_id_reads_as_a_move(self) -> None:
        _, migration = migrate_legacy_namespace({"enabledPlugins": {LEGACY_PLUGIN_ID: True}})

        assert migration.describe() == [
            f"enabledPlugins: {LEGACY_PLUGIN_ID} -> {CURRENT_PLUGIN_ID}"
        ]
