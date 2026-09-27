"""GH-1503: repair `*`-before-`:*` Bash rules without widening a grant."""

from __future__ import annotations

import pytest

from dev10x.skills.permission.star_prefix import (
    is_unmatchable,
    repair_star_prefix,
    space_form,
)

# The shapes observed in the supervisor's user settings, paths generalised.
ALLOWS = [
    "Bash(~/.claude/tools/*:*)",
    "Bash(/tmp/Dev10x/**/*.py:*)",
    "Bash(curl -s*example.test:*)",
    "Bash(uv run --directory * pytest:*)",
]


class TestSpaceForm:
    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            ("Bash(mv * /dev/null:*)", "Bash(mv * /dev/null*)"),
            ("Bash(cp * ~/.claude:*)", "Bash(cp * ~/.claude*)"),
            ("Bash(chmod * /home/u/.claude:*)", "Bash(chmod * /home/u/.claude*)"),
            ("Bash(rm -rf /work/**:*)", "Bash(rm -rf /work/**)"),
        ],
    )
    def test_matches_the_harness_suggestion(self, rule: str, expected: str) -> None:
        assert space_form(rule) == expected

    def test_the_rewrite_is_no_longer_unmatchable(self) -> None:
        assert is_unmatchable(space_form("Bash(mv * /dev/null:*)")) is False


class TestIsUnmatchable:
    @pytest.mark.parametrize(
        "rule",
        ["Bash(git log:*)", "Bash(rg --files *)", "Read(~/x/**)", "Bash(mv * /dev/null*)"],
    )
    def test_ordinary_rules_are_left_alone(self, rule: str) -> None:
        assert is_unmatchable(rule) is False


class TestRepair:
    def test_allows_are_dropped_not_widened(self) -> None:
        data = {"permissions": {"allow": [*ALLOWS, "Bash(git log:*)"]}}

        repaired, repair = repair_star_prefix(data)

        assert repaired["permissions"]["allow"] == ["Bash(git log:*)"]
        assert [fix.dropped for fix in repair.fixes] == [True] * len(ALLOWS)

    @pytest.mark.parametrize("list_name", ["deny", "ask"])
    def test_guardrails_are_rewritten_in_place(self, list_name: str) -> None:
        data = {"permissions": {list_name: ["Bash(sudo:*)", "Bash(cp * ~/.claude:*)"]}}

        repaired, _ = repair_star_prefix(data)

        assert repaired["permissions"][list_name] == ["Bash(sudo:*)", "Bash(cp * ~/.claude*)"]

    def test_a_deny_is_never_lost(self) -> None:
        denies = ["Bash(mv * /dev/null:*)", "Bash(rm -rf /work/**:*)"]

        repaired, _ = repair_star_prefix({"permissions": {"deny": denies}})

        assert len(repaired["permissions"]["deny"]) == len(denies)

    def test_rewrite_already_listed_collapses(self) -> None:
        data = {"permissions": {"ask": ["Bash(cp * ~/.claude:*)", "Bash(cp * ~/.claude*)"]}}

        repaired, repair = repair_star_prefix(data)

        assert repaired["permissions"]["ask"] == ["Bash(cp * ~/.claude*)"]
        assert repair.fixes[0].pruned is True

    def test_input_is_not_mutated(self) -> None:
        data = {"permissions": {"deny": ["Bash(mv * /dev/null:*)"]}}

        repair_star_prefix(data)

        assert data == {"permissions": {"deny": ["Bash(mv * /dev/null:*)"]}}

    def test_non_string_entries_pass_through(self) -> None:
        repaired, _ = repair_star_prefix({"permissions": {"allow": [7, "Bash(a*:*)"]}})

        assert repaired["permissions"]["allow"] == [7]

    @pytest.mark.parametrize(
        "data",
        [{}, {"permissions": "nope"}, {"permissions": {"deny": "nope"}}],
    )
    def test_malformed_shapes_are_left_alone(self, data: dict) -> None:
        repaired, repair = repair_star_prefix(data)

        assert repaired == data
        assert repair.changed is False

    def test_a_second_pass_is_a_no_op(self) -> None:
        data = {
            "permissions": {
                "allow": ALLOWS,
                "deny": ["Bash(mv * /dev/null:*)"],
                "ask": ["Bash(rm -rf /work/**:*)", "Bash(cp * ~/.claude:*)"],
            }
        }
        once, _ = repair_star_prefix(data)

        twice, repair = repair_star_prefix(once)

        assert twice == once
        assert repair.changed is False


class TestDescribe:
    def test_every_drop_and_rewrite_is_named(self) -> None:
        data = {
            "permissions": {
                "deny": ["Bash(mv * /dev/null:*)"],
                "ask": ["Bash(cp * ~/.claude:*)", "Bash(cp * ~/.claude*)"],
                "allow": ["Bash(~/.claude/tools/*:*)"],
            }
        }

        _, repair = repair_star_prefix(data)

        assert repair.count == 3
        assert repair.describe() == [
            "deny: Bash(mv * /dev/null:*) -> Bash(mv * /dev/null*)",
            "ask: pruned Bash(cp * ~/.claude:*) (Bash(cp * ~/.claude*) already present)",
            "allow: dropped Bash(~/.claude/tools/*:*) "
            "(a `*` before `:*` never matches; the space form would widen it)",
        ]
