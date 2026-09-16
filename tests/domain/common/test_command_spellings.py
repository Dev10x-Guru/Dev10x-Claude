"""One catalog entry renders every spelling of a command (GH-1317).

The expansion is a source-shape change, so the tests split in two:
:class:`TestRendering` pins what a ``command_spellings:`` block emits,
and :class:`TestBackwardCompatibility` pins what it must NOT disturb —
a catalog without the key, and a userspace copy written before the
schema existed.
"""

from __future__ import annotations

from dev10x.domain.common.command_spellings import (
    expand_spellings,
    render_spelling_rules,
)
from dev10x.skills.permission.catalog_merge import (
    compute_drift,
    merge_catalogs,
    unclassified_shipped_keys,
)


class TestRendering:
    def test_one_command_renders_a_rule_per_prefix(self) -> None:
        rules = render_spelling_rules(
            entries=[{"prefixes": ["", "uvx ", "uv run "], "commands": ["dev10x init"]}]
        )
        assert rules == [
            "Bash(dev10x init:*)",
            "Bash(uvx dev10x init:*)",
            "Bash(uv run dev10x init:*)",
        ]

    def test_commands_without_prefixes_render_one_rule_each(self) -> None:
        # The ImageMagick shape: spellings that are distinct binaries.
        assert render_spelling_rules(entries=[{"commands": ["magick", "convert"]}]) == [
            "Bash(magick:*)",
            "Bash(convert:*)",
        ]

    def test_duplicate_pairs_render_once(self) -> None:
        rules = render_spelling_rules(
            entries=[
                {"commands": ["magick"]},
                {"prefixes": [""], "commands": ["magick"]},
            ]
        )
        assert rules == ["Bash(magick:*)"]

    def test_surrounding_whitespace_is_stripped_from_a_command(self) -> None:
        assert render_spelling_rules(entries=[{"commands": ["  dev10x init  "]}]) == [
            "Bash(dev10x init:*)"
        ]

    def test_an_empty_prefix_list_falls_back_to_the_bare_spelling(self) -> None:
        assert render_spelling_rules(entries=[{"prefixes": [], "commands": ["x"]}]) == [
            "Bash(x:*)"
        ]


class TestMalformedEntries:
    """A catalog is read by diagnostics; malformed input must not raise."""

    def test_a_non_list_block_renders_nothing(self) -> None:
        assert render_spelling_rules(entries="not-a-list") == []

    def test_a_non_mapping_entry_is_skipped(self) -> None:
        assert render_spelling_rules(entries=["nope", {"commands": ["x"]}]) == ["Bash(x:*)"]

    def test_non_string_commands_and_prefixes_are_dropped(self) -> None:
        assert render_spelling_rules(entries=[{"prefixes": [1, "p "], "commands": [2, "x"]}]) == [
            "Bash(p x:*)"
        ]

    def test_a_blank_command_renders_nothing(self) -> None:
        assert render_spelling_rules(entries=[{"commands": ["   "]}]) == []

    def test_a_missing_commands_key_renders_nothing(self) -> None:
        assert render_spelling_rules(entries=[{"prefixes": ["uvx "]}]) == []


class TestFlatExpansion:
    def test_rendered_rules_append_to_base_permissions(self) -> None:
        expanded = expand_spellings(
            {
                "base_permissions": ["Bash(existing:*)"],
                "command_spellings": [{"prefixes": ["uvx "], "commands": ["dev10x init"]}],
            }
        )
        assert expanded["base_permissions"] == [
            "Bash(existing:*)",
            "Bash(uvx dev10x init:*)",
        ]

    def test_the_source_key_is_consumed(self) -> None:
        # Downstream readers classify top-level keys by name; leaving the
        # source shape behind would surface as unclassified drift.
        expanded = expand_spellings({"command_spellings": [{"commands": ["x"]}]})
        assert "command_spellings" not in expanded

    def test_a_rule_already_listed_by_hand_is_not_duplicated(self) -> None:
        expanded = expand_spellings(
            {
                "base_permissions": ["Bash(x:*)"],
                "command_spellings": [{"commands": ["x"]}],
            }
        )
        assert expanded["base_permissions"] == ["Bash(x:*)"]

    def test_a_malformed_base_permissions_list_is_replaced_not_crashed(self) -> None:
        expanded = expand_spellings(
            {"base_permissions": "oops", "command_spellings": [{"commands": ["x"]}]}
        )
        assert expanded["base_permissions"] == ["Bash(x:*)"]


class TestGroupExpansion:
    def test_a_group_block_appends_to_that_groups_rules(self) -> None:
        expanded = expand_spellings(
            {
                "groups": {
                    "im": {
                        "tier": 2,
                        "rules": ["Bash(identify:*)"],
                        "command_spellings": [{"commands": ["magick", "convert"]}],
                    }
                }
            }
        )
        assert expanded["groups"]["im"]["rules"] == [
            "Bash(identify:*)",
            "Bash(magick:*)",
            "Bash(convert:*)",
        ]
        assert "command_spellings" not in expanded["groups"]["im"]

    def test_a_group_without_the_key_is_untouched(self) -> None:
        catalog = {
            "groups": {
                "a": {"rules": ["Bash(a:*)"]},
                "b": {"command_spellings": [{"commands": ["b"]}]},
            }
        }
        expanded = expand_spellings(catalog)
        assert expanded["groups"]["a"] == {"rules": ["Bash(a:*)"]}
        assert expanded["groups"]["b"]["rules"] == ["Bash(b:*)"]

    def test_a_non_mapping_group_is_carried_through(self) -> None:
        catalog = {
            "groups": {
                "broken": ["not", "a", "mapping"],
                "ok": {"command_spellings": [{"commands": ["x"]}]},
            }
        }
        assert expand_spellings(catalog)["groups"]["broken"] == ["not", "a", "mapping"]

    def test_a_group_with_a_missing_rules_key_gains_one(self) -> None:
        expanded = expand_spellings(
            {"groups": {"g": {"command_spellings": [{"commands": ["x"]}]}}}
        )
        assert expanded["groups"]["g"]["rules"] == ["Bash(x:*)"]


class TestBackwardCompatibility:
    def test_a_catalog_without_the_key_is_returned_unchanged(self) -> None:
        catalog = {"base_permissions": ["Bash(a:*)"], "groups": {"g": {"rules": ["Bash(b:*)"]}}}
        assert expand_spellings(catalog) is catalog

    def test_a_non_mapping_document_is_returned_unchanged(self) -> None:
        assert expand_spellings(None) is None

    def test_a_catalog_with_no_groups_key_is_returned_unchanged(self) -> None:
        catalog = {"base_permissions": ["Bash(a:*)"], "groups": "not-a-mapping"}
        assert expand_spellings(catalog) is catalog

    def test_an_old_shape_user_catalog_merges_against_the_new_shipped_shape(self) -> None:
        # The risk GH-1317 had to clear: nothing rewrites a user's
        # ~/.config/Dev10x/projects.yaml, so every existing copy predates
        # this schema. It must read as "behind by N rules", never as a
        # broken shape or as phantom drift.
        shipped = expand_spellings(
            {
                "base_permissions": ["Bash(kept:*)"],
                "command_spellings": [{"prefixes": ["", "uvx "], "commands": ["dev10x init"]}],
            }
        )
        user = {"base_permissions": ["Bash(kept:*)"], "roots": ["/work"]}

        drift = compute_drift(shipped=shipped, user=user)
        assert drift.missing_from_user == (
            "Bash(dev10x init:*)",
            "Bash(uvx dev10x init:*)",
        )
        assert drift.missing_sections == ()
        assert drift.unclassified_keys == ()

        merged = merge_catalogs(shipped=shipped, user=user).config
        assert merged["base_permissions"] == [
            "Bash(kept:*)",
            "Bash(dev10x init:*)",
            "Bash(uvx dev10x init:*)",
        ]
        assert merged["roots"] == ["/work"]

    def test_the_source_key_never_reaches_the_unclassified_check(self) -> None:
        shipped = expand_spellings({"command_spellings": [{"commands": ["x"]}]})
        assert unclassified_shipped_keys(shipped) == ()
