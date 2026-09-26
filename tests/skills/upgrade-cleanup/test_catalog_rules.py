"""Tests for catalog_rules.py: computing the rules the catalog expects —
script/Read rule builders, coverage checks, generalization, and stale-MCP-
wildcard expansion. No writes happen here (GH-1432, GH-1449)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.skills.permission.catalog_rules import (
    _expand_stale_wildcards,
    _generalizations,
    _unescaped_parens_balance,
    build_marketplaces_script_rules,
    build_script_allow_rules,
    collapse_double_slashes,
    generalize_permission,
    is_dead_glob_script_rule,
    is_well_formed_rule,
    scan_plugin_scripts,
    verify_script_coverage,
)


def _write_settings(path: Path, *, allow: list[str] | None = None, **sections: object) -> Path:
    permissions: dict[str, object] = {}
    if allow is not None:
        permissions["allow"] = allow
    permissions.update(sections)
    import json

    path.write_text(json.dumps({"permissions": permissions}))
    return path


class TestScanPluginScripts:
    def test_finds_scripts_across_globs(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "release.sh").write_text("#!/bin/sh\n")
        (tmp_path / "hooks" / "scripts").mkdir(parents=True)
        (tmp_path / "hooks" / "scripts" / "hook.py").write_text("")
        (tmp_path / "skills" / "foo" / "scripts").mkdir(parents=True)
        (tmp_path / "skills" / "foo" / "scripts" / "run.sh").write_text("")

        scripts = scan_plugin_scripts(tmp_path)

        names = {p.name for p in scripts}
        assert names == {"release.sh", "hook.py", "run.sh"}

    def test_returns_sorted_unique(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "a.sh").write_text("")
        (tmp_path / "bin" / "b.sh").write_text("")
        scripts = scan_plugin_scripts(tmp_path)
        assert scripts == sorted(scripts)

    def test_empty_when_no_scripts(self, tmp_path: Path) -> None:
        assert scan_plugin_scripts(tmp_path) == []


class TestBuildScriptAllowRules:
    def test_builds_bash_rule_per_script(self, tmp_path: Path) -> None:
        (tmp_path / "bin").mkdir()
        script = tmp_path / "bin" / "release.sh"
        script.write_text("")
        rules = build_script_allow_rules([script], plugin_root=tmp_path)
        assert rules == [f"Bash({tmp_path}/bin/release.sh:*)"]

    def test_empty_for_no_scripts(self, tmp_path: Path) -> None:
        assert build_script_allow_rules([], plugin_root=tmp_path) == []

    def test_collapses_double_slash_from_trailing_root(self, tmp_path: Path) -> None:
        # GH-704: a plugin_root carrying a trailing slash must not emit `//`.
        root = Path(f"{tmp_path}/")
        (tmp_path / "bin").mkdir()
        script = tmp_path / "bin" / "release.sh"
        script.write_text("")
        rules = build_script_allow_rules([script], plugin_root=root)
        assert "//" not in rules[0]
        assert rules == [f"Bash({tmp_path}/bin/release.sh:*)"]


class TestCollapseDoubleSlashes:
    def test_collapses_runs(self) -> None:
        assert collapse_double_slashes("/a//b///c") == "/a/b/c"

    def test_preserves_scheme(self) -> None:
        assert collapse_double_slashes("https://x//y") == "https://x/y"

    def test_noop_on_clean(self) -> None:
        assert collapse_double_slashes("/a/b/c") == "/a/b/c"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            # GH-704 is always mid-token — the source of pollution this
            # helper exists to normalize (`.../<ver>//skills/...`).
            (
                "~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.79.0//skills/foo/scripts/x.sh",
                "~/.claude/plugins/cache/Dev10x-Guru/Dev10x/0.79.0/skills/foo/scripts/x.sh",
            ),
            # A scheme buried mid-path (not just at the start) is still
            # left untouched by the `(?<!:)` guard.
            (
                "Bash(mcp://server//tool:*)",
                "Bash(mcp://server/tool:*)",
            ),
            # Multiple separate double-slash runs each collapse.
            ("//a//b", "/a/b"),
        ],
    )
    def test_scoped_collapse_matches_documented_cases(self, path: str, expected: str) -> None:
        assert collapse_double_slashes(path) == expected


class TestBuildMarketplacesScriptRules:
    def test_emits_unversioned_marketplace_twins(self, tmp_path: Path) -> None:
        # GH-704: seed both root forms so cache- and marketplace-dispatched
        # scripts both match a grant.
        plugin_cache = "~/.claude/plugins/cache/Dev10x-Guru/Dev10x"
        plugin_root = tmp_path / "Dev10x-Guru" / "Dev10x" / "0.79.0"
        (plugin_root / "skills" / "foo" / "scripts").mkdir(parents=True)
        script = plugin_root / "skills" / "foo" / "scripts" / "bar.py"
        script.write_text("")
        home = tmp_path / "home"
        home.mkdir()
        rules = build_marketplaces_script_rules(
            [script],
            plugin_root=plugin_root,
            plugin_cache=plugin_cache,
            user_home=home,
        )
        rel = ".claude/plugins/marketplaces/Dev10x-Guru/skills/foo/scripts/bar.py"
        assert rules == [
            f"Bash(~/{rel}:*)",
            f"Bash({home}/{rel}:*)",
        ]
        assert all("//" not in rule for rule in rules)

    def test_empty_when_publisher_unresolvable(self, tmp_path: Path) -> None:
        script = tmp_path / "x.py"
        script.write_text("")
        assert (
            build_marketplaces_script_rules(
                [script],
                plugin_root=tmp_path,
                plugin_cache="/not/a/cache/path",
                user_home=tmp_path,
            )
            == []
        )


class TestIsDeadGlobScriptRule:
    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(~/.claude/plugins/cache/Pub/Plug/**/scripts/x.sh:*)",
            "Bash(/home/u/.claude/plugins/cache/Pub/Plug/**:*)",
        ],
    )
    def test_true_for_dead_glob(self, entry: str) -> None:
        assert is_dead_glob_script_rule(entry) is True

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(~/.claude/plugins/cache/Pub/Plug/0.1.0/scripts/x.sh:*)",
            "Read(~/.claude/plugins/marketplaces/Pub/**)",
            "Bash(git status:*)",
        ],
    )
    def test_false_for_functional_rule(self, entry: str) -> None:
        assert is_dead_glob_script_rule(entry) is False


class TestVerifyScriptCoverage:
    def test_reports_covered_and_missing(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=["Bash(/any/path/release.sh:*)"],
        )
        covered, missing = verify_script_coverage(
            path,
            ["Bash(/plugin/bin/release.sh:*)", "Bash(/plugin/bin/other.sh:*)"],
        )
        assert covered == ["Bash(/plugin/bin/release.sh:*)"]
        assert missing == ["Bash(/plugin/bin/other.sh:*)"]

    def test_exact_match_counts_as_covered(self, tmp_path: Path) -> None:
        rule = "Bash(/plugin/bin/release.sh:*)"
        path = _write_settings(tmp_path / "settings.local.json", allow=[rule])
        covered, missing = verify_script_coverage(path, [rule])
        assert covered == [rule]
        assert missing == []

    def test_dead_glob_is_not_coverage(self, tmp_path: Path) -> None:
        path = _write_settings(
            tmp_path / "settings.local.json",
            allow=["Bash(~/.claude/plugins/cache/Pub/Plug/**/release.sh:*)"],
        )
        covered, missing = verify_script_coverage(path, ["Bash(/plugin/bin/release.sh:*)"])
        assert covered == []
        assert missing == ["Bash(/plugin/bin/release.sh:*)"]

    def test_invalid_json_treats_all_as_missing(self, tmp_path: Path) -> None:
        bad = tmp_path / "settings.local.json"
        bad.write_text("{invalid")
        covered, missing = verify_script_coverage(bad, ["Bash(x:*)"])
        assert covered == []
        assert missing == ["Bash(x:*)"]


class TestGeneralizePermission:
    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            ("Bash(/p/foo.sh arg1 arg2:*)", "Bash(/p/foo.sh:*)"),
            ("Bash(/p/run.py --flag value:*)", "Bash(/p/run.py:*)"),
            ("Bash(git reset --soft abc123def0:*)", "Bash(git reset --soft:*)"),
        ],
    )
    def test_generalizes_known_patterns(self, entry: str, expected: str) -> None:
        assert generalize_permission(entry) == expected

    def test_returns_none_when_no_change(self) -> None:
        assert generalize_permission("Bash(git status:*)") is None

    def test_escaped_parens_survive_generalization(self) -> None:
        entry = "Bash(/p/q.py --sql SELECT COUNT\\(*\\) FROM t | tail -20:*)"
        assert generalize_permission(entry) == "Bash(/p/q.py:*)"

    def test_escaped_parens_do_not_strand_the_tail(self) -> None:
        entry = "Bash(/p/q.py --sql JSON_VALUE\\(c,'$.k'\\):*)"
        assert generalize_permission(entry) == "Bash(/p/q.py:*)"


class TestWellFormedRule:
    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(/p/foo.sh:*)",
            "Bash(/p/q.py --sql COUNT\\(*\\):*)",
            "Read(/p/**)",
        ],
    )
    def test_accepts_valid_rules(self, entry: str) -> None:
        assert is_well_formed_rule(entry)

    @pytest.mark.parametrize(
        "entry",
        [
            'Bash(/p/q.py:*)" | tail -20)',
            "Bash(/p/foo.sh:*",
            "/p/foo.sh:*)",
            "Bash(/p/foo.sh:*))",
        ],
    )
    def test_rejects_malformed_rules(self, entry: str) -> None:
        assert not is_well_formed_rule(entry)


class TestUnescapedParensBalance:
    """Direct coverage of the balance-checking primitive `is_well_formed_rule`
    delegates to — previously exercised only through that composed check
    (GH-1449)."""

    @pytest.mark.parametrize(
        "entry",
        [
            "()",
            "(a(b)c)",
            "no parens here",
            "escaped \\( is not a paren",
            "\\(\\)",
        ],
    )
    def test_true_for_balanced_or_fully_escaped(self, entry: str) -> None:
        assert _unescaped_parens_balance(entry) is True

    @pytest.mark.parametrize(
        "entry",
        [
            "(",
            ")",
            "(a(b)",
            "a)b(",
        ],
    )
    def test_false_for_unbalanced(self, entry: str) -> None:
        assert _unescaped_parens_balance(entry) is False

    def test_trailing_backslash_does_not_index_error(self) -> None:
        # A lone trailing backslash advances the index by 2 (GH-1449
        # regression guard) — must not raise IndexError on the odd-length
        # walk off the end of the string.
        assert _unescaped_parens_balance("trailing\\") is True


class TestGeneralizations:
    """Direct coverage of the batch helper `generalize_permissions` (in
    catalog_write.py) delegates to — previously exercised only end-to-end
    through the file-writing wrapper (GH-1449)."""

    def test_returns_safe_rewrite(self) -> None:
        replacements, refused = _generalizations(["Bash(/p/foo.sh arg1:*)"])
        assert replacements == [("Bash(/p/foo.sh arg1:*)", "Bash(/p/foo.sh:*)")]
        assert refused == []

    def test_skips_entries_with_no_change(self) -> None:
        replacements, refused = _generalizations(["Bash(git status:*)"])
        assert replacements == []
        assert refused == []

    def test_skips_when_generalized_form_already_present(self) -> None:
        replacements, refused = _generalizations(["Bash(/p/foo.sh arg1:*)", "Bash(/p/foo.sh:*)"])
        assert replacements == []

    def test_refuses_malformed_generalized_output(self) -> None:
        # A hand-crafted entry whose generalized form comes out malformed
        # must be refused, not silently written (GH-1150).
        with patch(
            "dev10x.skills.permission.catalog_rules.generalize_permission",
            return_value="not-a-well-formed-rule",
        ):
            replacements, refused = _generalizations(["Bash(/p/foo.sh arg1:*)"])
        assert replacements == []
        assert refused == ["Bash(/p/foo.sh arg1:*)"]


class TestExpandStaleWildcards:
    """Direct coverage of the wildcard-expansion helper — previously
    untested (GH-1449). Avoids the round-trip where ensure-base strips a
    stale `mcp__plugin_X_*` wildcard and a follow-up enumerate-mcp call
    would have to re-add the same tools."""

    def test_disabled_returns_empty(self) -> None:
        assert (
            _expand_stale_wildcards(
                stale_wildcards=["mcp__plugin_Dev10x_*"],
                existing=set(),
                enabled=False,
            )
            == []
        )

    def test_no_stale_wildcards_returns_empty(self) -> None:
        assert (
            _expand_stale_wildcards(
                stale_wildcards=[],
                existing=set(),
                enabled=True,
            )
            == []
        )

    def test_expands_wildcard_into_catalog_tools_not_already_present(self) -> None:
        catalog = {"cli": ["mcp__plugin_Dev10x_cli__issue_get", "mcp__plugin_Dev10x_cli__pr_get"]}
        with patch(
            "dev10x.skills.permission.enumerate_mcp._matches_wildcard",
            return_value=["mcp__plugin_Dev10x_cli__issue_get", "mcp__plugin_Dev10x_cli__pr_get"],
        ):
            expanded = _expand_stale_wildcards(
                stale_wildcards=["mcp__plugin_Dev10x_*"],
                existing={"mcp__plugin_Dev10x_cli__issue_get"},
                enabled=True,
                catalog=catalog,
            )
        assert expanded == ["mcp__plugin_Dev10x_cli__pr_get"]

    def test_empty_catalog_returns_empty(self) -> None:
        assert (
            _expand_stale_wildcards(
                stale_wildcards=["mcp__plugin_Dev10x_*"],
                existing=set(),
                enabled=True,
                catalog={},
            )
            == []
        )

    def test_discovers_catalog_when_not_passed(self) -> None:
        with (
            patch(
                "dev10x.skills.permission.enumerate_mcp.discover_mcp_tools",
                return_value={"cli": ["mcp__plugin_Dev10x_cli__issue_get"]},
            ),
            patch(
                "dev10x.skills.permission.enumerate_mcp._matches_wildcard",
                return_value=["mcp__plugin_Dev10x_cli__issue_get"],
            ),
        ):
            expanded = _expand_stale_wildcards(
                stale_wildcards=["mcp__plugin_Dev10x_*"],
                existing=set(),
                enabled=True,
            )
        assert expanded == ["mcp__plugin_Dev10x_cli__issue_get"]
