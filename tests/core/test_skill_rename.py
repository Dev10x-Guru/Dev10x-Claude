"""`dev10x skill rename` rewrite engine (ADR-0034 Stage A4, GH-1558)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.core.plugin_map import PluginMap, load_plugin_map
from dev10x.core.skill_rename import (
    InvocationName,
    RenamePlan,
    count_mentions,
    parse_invocation_name,
    plan_rename,
    plan_rename_from_text,
    rename_scope,
    rewrite_text,
)

GOG = InvocationName(plugin="dev10x", skill="gog")
COMM_GOG = InvocationName(plugin="dev10x-comm", skill="gog")

FIXTURE_FILES = {
    "skills/gog/SKILL.md": (
        "---\nname: dev10x:gog\n---\nUse Dev10x:gog or Skill(dev10x:gog).\n"
        "Not dev10x:gog-extra, not my.dev10x:gog.\n"
    ),
    "skills/gog/evals/evals.json": '{"skill": "dev10x:gog"}\n',
    "skills/work-on/references/playbook.d/coding.yaml": "- skill: dev10x:gog\n",
    "docs/guide.md": "Call dev10x:gog, then dev10x:git.\n",
    "src/dev10x/core/validators/command-skill-map.yaml": "skill: dev10x:gog\n",
    "src/dev10x/core/validators/command-skill-map.d/comm.yaml": "skill: dev10x:gog\n",
    ".claude/rules/naming.md": "Rules mention dev10x:gog too.\n",
    "src/dev10x/other.py": "# dev10x:gog in source stays put\n",
}


def _snapshot(*, root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def plugin_map() -> PluginMap:
    return load_plugin_map()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for relative, content in FIXTURE_FILES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


@pytest.fixture
def plan(tree: Path) -> RenamePlan:
    result = plan_rename(root=tree, old=GOG, new=COMM_GOG)
    assert isinstance(result, SuccessResult)
    return result.value


class TestParseInvocationName:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("dev10x:gog", GOG),
            ("gog", GOG),
            ("dev10x-comm:gog", COMM_GOG),
            (
                "dev10x-teach:skill-create",
                InvocationName(plugin="dev10x-teach", skill="skill-create"),
            ),
        ],
    )
    def test_accepts(
        self,
        plugin_map: PluginMap,
        text: str,
        expected: InvocationName,
    ) -> None:
        result = parse_invocation_name(text=text, plugin_names=plugin_map.known_plugin_names())

        assert result == SuccessResult(value=expected)

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("qa:tts", "unknown plugin 'qa'"),
            ("dev10x-nowhere:tts", "unknown plugin 'dev10x-nowhere'"),
            ("dev10x:Bad_Name", "is not a skill name"),
            ("dev10x:-x", "is not a skill name"),
        ],
    )
    def test_rejects(self, plugin_map: PluginMap, text: str, message: str) -> None:
        result = parse_invocation_name(text=text, plugin_names=plugin_map.known_plugin_names())

        assert isinstance(result, ErrorResult)
        assert message in result.error


class TestRewriteText:
    @pytest.mark.parametrize(
        ("text", "expected", "count"),
        [
            ("Skill(dev10x:gog)", "Skill(dev10x-comm:gog)", 1),
            ("`Dev10x:gog`", "`Dev10x-comm:gog`", 1),
            ("dev10x:gog-extra", "dev10x:gog-extra", 0),
            ("my.dev10x:gog", "my.dev10x:gog", 0),
            ("dev10x:gogx", "dev10x:gogx", 0),
            ("dev10x:gog dev10x:gog", "dev10x-comm:gog dev10x-comm:gog", 2),
        ],
    )
    def test_rewrites_only_whole_names(self, text: str, expected: str, count: int) -> None:
        assert rewrite_text(text=text, old=GOG, new=COMM_GOG) == (expected, count)

    def test_reverse_restores_the_capital(self) -> None:
        forward, _ = rewrite_text(text="Dev10x:gog", old=GOG, new=COMM_GOG)

        assert rewrite_text(text=forward, old=COMM_GOG, new=GOG) == ("Dev10x:gog", 1)


class TestRenameScope:
    def test_covers_inventory_scope_and_map_fragments(self, tree: Path) -> None:
        scope = {path.relative_to(tree).as_posix() for path in rename_scope(root=tree)}

        assert scope == {
            "skills/gog/SKILL.md",
            "skills/gog/evals/evals.json",
            "skills/work-on/references/playbook.d/coding.yaml",
            "docs/guide.md",
            "src/dev10x/core/validators/command-skill-map.yaml",
            "src/dev10x/core/validators/command-skill-map.d/comm.yaml",
        }

    def test_counts_mentions_in_scope(self, tree: Path) -> None:
        assert count_mentions(paths=rename_scope(root=tree), name=GOG) == 8


class TestDryRun:
    def test_writes_nothing(self, tree: Path) -> None:
        before = _snapshot(root=tree)

        plan_rename(root=tree, old=GOG, new=COMM_GOG)

        assert _snapshot(root=tree) == before

    def test_counts_every_replacement(self, plan: RenamePlan) -> None:
        assert (plan.replacements, len(plan.rewrites)) == (8, 6)

    def test_diff_shows_each_rewritten_line(self, plan: RenamePlan) -> None:
        diff = plan.diff()

        assert "--- a/skills/gog/SKILL.md\n+++ b/skills/gog/SKILL.md\n" in diff
        assert "-name: dev10x:gog\n+name: dev10x-comm:gog\n" in diff
        assert "+skill: dev10x-comm:gog\n" in diff

    def test_diff_skips_claude_dir(self, plan: RenamePlan) -> None:
        assert ".claude" not in plan.diff()


class TestApply:
    def test_rewrites_in_scope_files(self, tree: Path, plan: RenamePlan) -> None:
        plan.apply()

        assert (tree / "docs/guide.md").read_text() == "Call dev10x-comm:gog, then dev10x:git.\n"

    @pytest.mark.parametrize("relative", [".claude/rules/naming.md", "src/dev10x/other.py"])
    def test_leaves_out_of_scope_files(
        self,
        tree: Path,
        plan: RenamePlan,
        relative: str,
    ) -> None:
        plan.apply()

        assert (tree / relative).read_text() == FIXTURE_FILES[relative]

    def test_round_trip_leaves_zero_diff(self, tree: Path, plan: RenamePlan) -> None:
        before = _snapshot(root=tree)
        plan.apply()
        back = plan_rename(root=tree, old=COMM_GOG, new=GOG)
        assert isinstance(back, SuccessResult)

        back.value.apply()

        assert _snapshot(root=tree) == before


class TestRefusals:
    def test_refuses_a_target_already_in_use(self, tree: Path) -> None:
        result = plan_rename(root=tree, old=GOG, new=InvocationName(plugin="dev10x", skill="git"))

        assert isinstance(result, ErrorResult)
        assert "dev10x:git is already referenced 1 time(s)" in result.error

    def test_refuses_the_same_name(self, tree: Path) -> None:
        result = plan_rename(root=tree, old=GOG, new=GOG)

        assert result == ErrorResult(error="dev10x:gog and dev10x:gog are the same name")

    def test_a_name_without_mentions_plans_nothing(self, tree: Path) -> None:
        result = plan_rename(
            root=tree,
            old=InvocationName(plugin="dev10x", skill="tts"),
            new=InvocationName(plugin="dev10x-qa", skill="tts"),
        )

        assert isinstance(result, SuccessResult)
        assert result.value.rewrites == ()


class TestPlanFromText:
    def test_resolves_both_names_from_the_plugin_map(
        self,
        tree: Path,
        plugin_map: PluginMap,
    ) -> None:
        result = plan_rename_from_text(
            root=tree, old="gog", new="dev10x-comm:gog", plugin_map=plugin_map
        )

        assert isinstance(result, SuccessResult)
        assert (result.value.old, result.value.new) == (GOG, COMM_GOG)

    @pytest.mark.parametrize(
        ("old", "new", "message"),
        [
            ("nope:gog", "dev10x-comm:gog", "unknown plugin 'nope'"),
            ("dev10x:gog", "nope:gog", "unknown plugin 'nope'"),
        ],
    )
    def test_reports_the_bad_name(
        self,
        tree: Path,
        plugin_map: PluginMap,
        old: str,
        new: str,
        message: str,
    ) -> None:
        result = plan_rename_from_text(root=tree, old=old, new=new, plugin_map=plugin_map)

        assert isinstance(result, ErrorResult)
        assert message in result.error
