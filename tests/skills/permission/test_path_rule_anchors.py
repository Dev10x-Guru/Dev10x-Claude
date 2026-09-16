"""Path-rule anchor semantics and the GH-1325 compaction proof.

Three jobs, in order of what they protect:

- unit coverage of the anchor/depth reading itself;
- an equivalence proof that ``Read|Edit(//tmp/Dev10x/**)`` reaches every
  path the retired ten-namespace enumeration was meant to reach. A
  compaction that drops coverage is invisible: nothing errors, the
  affected command simply prompts on every call forever (GH-1153);
- counter-checks in the GH-1215 shape. That ticket records a guard
  passing 3/3 while its own discovery was blind to four fifths of the
  surface, so each catalog's rule set is measured twice — by scanning
  the raw text and by walking the parsed document — and the two must
  agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.domain.common.baseline_catalog import load_baseline_dict
from dev10x.domain.common.command_spellings import expand_spellings
from dev10x.skills.permission.catalog_paths import CATALOG_RELPATH
from dev10x.skills.permission.path_rule_anchors import (
    PATH_TOOLS,
    Anchor,
    PathRule,
    anchor_of,
    covered_by_any,
    covers,
    parse_path_rule,
    path_rules,
)

PERMISSION_DIR = Path(permission_pkg.__file__).resolve().parent
REPO_ROOT = PERMISSION_DIR.parents[3]
BASELINE_YAML = PERMISSION_DIR / "baseline-permissions.yaml"
PROJECTS_YAML = REPO_ROOT / CATALOG_RELPATH

#: A path rule as a YAML list item, quoted or bare. Anchored to the item
#: so prose inside a comment — `Edit(path) covers all file-editing
#: tools` — is not scraped as a declaration.
_PATH_RULE_ITEM = re.compile(
    r'^\s*-\s+"?((?:Read|Edit|Write)\([^)"]*\))"?\s*$',
    re.MULTILINE,
)


def _rules_in_text(*, source: Path) -> list[str]:
    return _PATH_RULE_ITEM.findall(source.read_text(encoding="utf-8"))


def _rules_in_parsed_yaml(*, source: Path) -> list[str]:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            if parse_path_rule(rule=node) is not None:
                found.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(yaml.safe_load(source.read_text(encoding="utf-8")))
    return found


#: The mktmp namespaces `base_permissions` enumerated one rule per tool
#: per namespace before GH-1325. Frozen here so the proof below cannot
#: quietly shrink to whatever the catalog happens to say today.
RETIRED_NAMESPACES: tuple[str, ...] = (
    "git",
    "review",
    "skill-audit",
    "playwright",
    "self-qa",
    "ticket-scope",
    "slack",
    "pr-monitor",
    "gh",
    "foreman",
)

REPLACEMENT_RULES: tuple[str, ...] = ("Read(//tmp/Dev10x/**)", "Edit(//tmp/Dev10x/**)")


def _catalog_rules() -> list[str]:
    config = expand_spellings(yaml.safe_load(PROJECTS_YAML.read_text(encoding="utf-8")))
    return list(config.get("base_permissions") or [])


class TestAnchorOf:
    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            ("//tmp/Dev10x/**", Anchor.FILESYSTEM),
            ("~/.claude/memory/**", Anchor.HOME),
            ("/tmp/Dev10x/**", Anchor.SETTINGS_SOURCE),
            ("src/**", Anchor.RELATIVE),
        ],
    )
    def test_classifies_each_leading_token(self, pattern: str, expected: Anchor) -> None:
        assert anchor_of(pattern=pattern) == expected


class TestParsePathRule:
    def test_reads_tool_and_pattern(self) -> None:
        rule = parse_path_rule(rule="  Read(//tmp/Dev10x/**)  ")
        assert rule == PathRule(
            tool="Read",
            pattern="//tmp/Dev10x/**",
            anchor=Anchor.FILESYSTEM,
        )

    @pytest.mark.parametrize("rule", ["Bash(git status:*)", "Skill(Dev10x:*)", "not a rule"])
    def test_ignores_a_non_path_rule(self, rule: str) -> None:
        assert parse_path_rule(rule=rule) is None

    def test_path_rules_keeps_only_the_path_tools(self) -> None:
        parsed = path_rules(rules=["Bash(git status:*)", "Write(//tmp/x/**)"])
        assert [rule.tool for rule in parsed] == ["Write"]

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [("//tmp/x/**", True), ("~/x/**", True), ("/tmp/x/**", False), ("x/**", False)],
    )
    def test_reports_whether_the_anchor_is_a_fixed_location(
        self,
        pattern: str,
        expected: bool,
    ) -> None:
        rule = parse_path_rule(rule=f"Read({pattern})")
        assert rule is not None
        assert rule.reaches_a_fixed_location is expected


class TestCovers:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/tmp/Dev10x/git/msg.txt", True),
            ("/tmp/Dev10x/foreman/run/manifest.json", True),
            ("/tmp/Dev10x/top.txt", True),
            ("/tmp/other/git/msg.txt", False),
        ],
    )
    def test_double_star_crosses_directories(self, path: str, expected: bool) -> None:
        rule = parse_path_rule(rule="Read(//tmp/Dev10x/**)")
        assert rule is not None
        assert covers(rule=rule, absolute_path=path) is expected

    def test_single_star_stays_inside_one_segment(self) -> None:
        rule = parse_path_rule(rule="Read(//tmp/Dev10x/*.txt)")
        assert rule is not None
        assert covers(rule=rule, absolute_path="/tmp/Dev10x/msg.txt") is True
        assert covers(rule=rule, absolute_path="/tmp/Dev10x/git/msg.txt") is False

    @pytest.mark.parametrize("pattern", ["/tmp/Dev10x/**", "~/tmp/Dev10x/**", "tmp/Dev10x/**"])
    def test_an_unanchored_rule_reaches_no_absolute_path(self, pattern: str) -> None:
        rule = parse_path_rule(rule=f"Read({pattern})")
        assert rule is not None
        assert covers(rule=rule, absolute_path="/tmp/Dev10x/git/msg.txt") is False

    def test_covered_by_any_matches_only_the_named_tool(self) -> None:
        rules = path_rules(rules=["Read(//tmp/Dev10x/**)"])
        assert covered_by_any(rules=rules, tool="Read", absolute_path="/tmp/Dev10x/a/b") is True
        assert covered_by_any(rules=rules, tool="Edit", absolute_path="/tmp/Dev10x/a/b") is False


class TestCompactionEquivalence:
    def test_replacements_cover_every_retired_namespace(self) -> None:
        rules = path_rules(rules=REPLACEMENT_RULES)
        uncovered = [
            (tool, path)
            for tool in ("Read", "Edit")
            for namespace in RETIRED_NAMESPACES
            for path in (
                f"/tmp/Dev10x/{namespace}/file.txt",
                f"/tmp/Dev10x/{namespace}/nested/file.txt",
            )
            if not covered_by_any(rules=rules, tool=tool, absolute_path=path)
        ]
        assert not uncovered, (
            "the compacted tree rules do not reach paths the retired "
            "per-namespace enumeration was granted for. A dropped grant is "
            "silent — the call simply prompts forever (GH-1153):\n"
            + "\n".join(f"  {tool} {path}" for tool, path in uncovered)
        )

    def test_the_catalog_ships_the_replacements(self) -> None:
        assert set(REPLACEMENT_RULES) <= set(_catalog_rules())

    def test_the_catalog_no_longer_enumerates_the_namespaces(self) -> None:
        rules = set(_catalog_rules())
        stale = {
            f"{tool}(/tmp/Dev10x/{namespace}/**)"
            for tool in ("Read", "Edit")
            for namespace in RETIRED_NAMESPACES
        } & rules
        assert not stale, (
            "the per-namespace enumeration is back. One tree rule covers "
            "them, and re-enumerating reintroduces the GH-1095 maintenance "
            "trap where a new mktmp namespace prompts on every run:\n" + "\n".join(sorted(stale))
        )


class TestAnchorRatchet:
    @pytest.mark.parametrize("source", [PROJECTS_YAML, BASELINE_YAML])
    def test_no_dev10x_temp_rule_anchors_at_the_settings_source(self, source: Path) -> None:
        misanchored = [
            rule.pattern
            for rule in path_rules(rules=_rules_in_parsed_yaml(source=source))
            if rule.anchor is Anchor.SETTINGS_SOURCE and rule.pattern.startswith("/tmp/Dev10x")
        ]
        assert not misanchored, (
            f"{source.name} anchors a /tmp/Dev10x path rule with a single "
            "leading slash, which resolves against the settings source "
            "rather than the filesystem root — the rule grants nothing. Use "
            "`//tmp/Dev10x/...` (GH-1325):\n" + "\n".join(sorted(misanchored))
        )


class TestEnumerationCannotNarrow:
    @pytest.mark.parametrize("source", [PROJECTS_YAML, BASELINE_YAML])
    def test_two_independent_measurements_agree(self, source: Path) -> None:
        in_text = set(_rules_in_text(source=source))
        in_yaml = set(_rules_in_parsed_yaml(source=source))
        assert in_yaml, f"no path rules found in {source}"
        assert in_yaml == in_text, (
            f"the text scan and the parsed-document walk disagree about which "
            f"path rules {source.name} declares. Whichever is narrower makes "
            "the anchor ratchet and the compaction proof pass green while "
            "blind to the rules it cannot see (GH-1215).\n"
            f"  only in the parsed document: {sorted(in_yaml - in_text)}\n"
            f"  only in the text scan: {sorted(in_text - in_yaml)}"
        )

    def test_every_path_tool_is_parsed(self) -> None:
        parsed = path_rules(rules=[f"{tool}(//tmp/x/**)" for tool in PATH_TOOLS])
        assert [rule.tool for rule in parsed] == list(PATH_TOOLS)

    def test_the_baseline_and_the_catalog_agree_on_the_temp_tree(self) -> None:
        baseline = load_baseline_dict(BASELINE_YAML, strict=True)
        groups = baseline.get("groups") or {}
        declared = {
            rule
            for group in groups.values()
            if isinstance(group, dict)
            for rule in (group.get("rules") or [])
        }
        assert set(REPLACEMENT_RULES) <= declared
