from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.validators.agent_brief import (
    AgentBriefValidator,
    effective_entries,
    find_unnamed_skills,
    parse_entries,
)

from dev10x.domain import HookHint, HookInput, HookResult
from dev10x.validators import agent_brief


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


@pytest.fixture
def write_prefs() -> Callable[..., None]:
    def write(*, section: dict[str, Any]) -> None:
        friction = Dev10xConfigDir.friction_yaml()
        friction.parent.mkdir(parents=True, exist_ok=True)
        friction.write_text(
            yaml.safe_dump({"projects": [{"match": ["*/repo"], "dx020": section}]})
        )

    return write


@pytest.fixture(autouse=True)
def _fresh_defaults() -> Iterator[None]:
    agent_brief.default_entries.cache_clear()
    yield
    agent_brief.default_entries.cache_clear()


@pytest.fixture
def validator() -> AgentBriefValidator:
    return AgentBriefValidator()


def _agent_call(*, prompt: Any, cwd: Path | str = "", description: str = "") -> HookInput:
    return HookInput.from_dict(
        data={
            "tool_name": "Agent",
            "tool_input": {"prompt": prompt, "description": description},
        },
        cwd=str(cwd),
    )


class TestShouldRun:
    @pytest.mark.parametrize(
        ("tool_name", "expected"),
        [("Agent", True), ("Bash", False), ("Skill", False)],
    )
    def test_runs_only_for_agent(
        self, validator: AgentBriefValidator, tool_name: str, expected: bool
    ) -> None:
        inp = HookInput.from_dict(data={"tool_name": tool_name, "tool_input": {}})

        assert validator.should_run(inp) is expected


class TestAdvisoryMode:
    def test_unnamed_skill_returns_hint(
        self, validator: AgentBriefValidator, checkout: Path
    ) -> None:
        result = validator.validate(
            _agent_call(prompt="Write a Playwright script to record the flow.", cwd=checkout)
        )

        assert isinstance(result, HookHint)
        assert result.rule_id == "DX020"
        assert "`Playwright` → `dev10x-qa:qa-self`" in result.message
        assert "stop and report if a hook blocks a command" in result.message

    def test_description_is_read_too(self, validator: AgentBriefValidator, checkout: Path) -> None:
        result = validator.validate(
            _agent_call(prompt="Do the work.", description="git commit the fix", cwd=checkout)
        )

        assert isinstance(result, HookHint)
        assert "`dev10x:git-commit`" in result.message

    @pytest.mark.parametrize(
        "prompt",
        [
            "Use Skill(dev10x-qa:qa-self) to run the Playwright walkthrough.",
            "Run the playwright flow through qa-self.",
            "Commit the changes via Skill(dev10x:git-commit).",
            "Run pytest through the run_tests MCP tool.",
            "Summarize the module structure.",
            "Write a Playwright test.\ndev10x-ok: the test file itself is the deliverable",
            "",
        ],
    )
    def test_compliant_brief_passes(
        self, validator: AgentBriefValidator, checkout: Path, prompt: str
    ) -> None:
        assert validator.validate(_agent_call(prompt=prompt, cwd=checkout)) is None

    @pytest.mark.parametrize(
        "prompt",
        [
            "Run pytest on the module.\ndev10x-ok:",
            "dev10x-ok:\nRun pytest on the module.",
        ],
    )
    def test_escape_without_reason_still_flags(
        self, validator: AgentBriefValidator, checkout: Path, prompt: str
    ) -> None:
        result = validator.validate(_agent_call(prompt=prompt, cwd=checkout))

        assert isinstance(result, HookHint)

    @pytest.mark.parametrize("tool_input", [None, "prompt", {"prompt": 7}])
    def test_malformed_tool_input_passes(
        self, validator: AgentBriefValidator, tool_input: Any
    ) -> None:
        inp = HookInput(tool_name="Agent", command="", raw={"tool_input": tool_input})

        assert validator.validate(inp) is None

    def test_no_cwd_uses_defaults(self, validator: AgentBriefValidator) -> None:
        result = validator.validate(_agent_call(prompt="git push the branch"))

        assert isinstance(result, HookHint)


class TestProjectConfig:
    def test_deny_mode_blocks(
        self, validator: AgentBriefValidator, checkout: Path, write_prefs: Callable[..., None]
    ) -> None:
        write_prefs(section={"mode": "deny"})

        result = validator.validate(_agent_call(prompt="Open a draft PR.", cwd=checkout))

        assert isinstance(result, HookResult)
        assert result.rule_id == "DX020"
        assert "DEV10X_HOOK_DISABLE=DX020" in result.message

    def test_linked_worktree_reads_its_main_checkout_entry(
        self,
        validator: AgentBriefValidator,
        checkout: Path,
        write_prefs: Callable[..., None],
        tmp_path: Path,
    ) -> None:
        write_prefs(section={"mode": "deny"})
        worktree = tmp_path / "wt-elsewhere"
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {checkout}/.git/worktrees/wt-elsewhere\n")

        result = validator.validate(_agent_call(prompt="Open a draft PR.", cwd=worktree))

        assert isinstance(result, HookResult)

    def test_removed_skill_is_not_checked(
        self, validator: AgentBriefValidator, checkout: Path, write_prefs: Callable[..., None]
    ) -> None:
        write_prefs(section={"skill_keywords": {"remove": ["dev10x:py-test"]}})

        assert validator.validate(_agent_call(prompt="Run pytest.", cwd=checkout)) is None

    def test_added_entry_is_checked(
        self, validator: AgentBriefValidator, checkout: Path, write_prefs: Callable[..., None]
    ) -> None:
        write_prefs(
            section={
                "skill_keywords": {
                    "add": [{"skill": "my:deploy", "patterns": [r"\bkubectl apply\b"]}]
                }
            }
        )

        result = validator.validate(_agent_call(prompt="kubectl apply the chart", cwd=checkout))

        assert isinstance(result, HookHint)
        assert "`my:deploy`" in result.message


class TestEffectiveEntries:
    @pytest.mark.parametrize(
        "section",
        [{}, {"skill_keywords": "x"}, {"skill_keywords": {"remove": "dev10x:git"}}],
    )
    def test_malformed_overrides_keep_defaults(self, section: dict[str, Any]) -> None:
        assert effective_entries(section=section) == agent_brief.default_entries()


class TestParseEntries:
    def test_skips_malformed_items(self) -> None:
        entries = parse_entries(
            raw=[
                "not-a-dict",
                {"patterns": ["x"]},
                {"skill": "a:b"},
                {"skill": "a:c", "patterns": ["(", 3, ""]},
                {"skill": "a:d", "patterns": ["deploy"], "accept": ["ship", 4]},
                {"skill": "a:e", "patterns": ["roll"], "accept": "nope"},
            ]
        )

        assert [(entry.skill, entry.accept) for entry in entries] == [
            ("a:d", ("ship",)),
            ("a:e", ()),
        ]

    def test_non_list_is_empty(self) -> None:
        assert parse_entries(raw={"skill": "a:b"}) == ()


class TestDefaultMap:
    def test_missing_file_yields_no_entries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(agent_brief, "MAP_PATH", tmp_path / "absent.yaml")

        assert agent_brief.default_entries() == ()

    def test_non_mapping_document_yields_no_entries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "map.yaml"
        path.write_text("- just a list\n")
        monkeypatch.setattr(agent_brief, "MAP_PATH", path)

        assert agent_brief.default_entries() == ()

    def test_every_shipped_entry_compiles(self) -> None:
        document = yaml.safe_load(agent_brief.MAP_PATH.read_text())

        assert len(agent_brief.default_entries()) == len(document["entries"])


class TestNameTokens:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Use Skill(dev10x:git-commit).", ("use", "skill", "dev10x:git-commit")),
            (
                "call `mcp__plugin_dev10x_cli__push_safe`",
                ("call", "mcp__plugin_dev10x_cli__push_safe"),
            ),
            ("dev10x-ok: -- done:", ("dev10x-ok", "done")),
            ("edit src/a.py, then /x/.", ("edit", "src/a.py", "then", "/x")),
            ("run ./push_safe -- now:", ("run", "./push_safe", "now")),
            ("", ()),
        ],
    )
    def test_keeps_names_whole_and_trims_edges(self, text: str, expected: tuple[str, ...]) -> None:
        assert agent_brief.name_tokens(text=text) == expected


class TestSkillKeywordNames:
    @pytest.fixture()
    def entry(self) -> agent_brief.SkillKeyword:
        return agent_brief.SkillKeyword(
            skill="A:B", patterns=(), accept=("()", "x", "Skill(test)", "-y-")
        )

    def test_single_token_names_compare_whole(self, entry: agent_brief.SkillKeyword) -> None:
        assert entry.token_names == frozenset({"a:b", "x"})

    def test_other_names_match_verbatim(self, entry: agent_brief.SkillKeyword) -> None:
        assert entry.literal_names == ("Skill(test)", "-y-")

    @pytest.mark.parametrize(
        ("brief", "expected"),
        [
            pytest.param("use Skill(test) here", True, id="first-literal"),
            pytest.param("use -y- here", True, id="second-literal"),
            pytest.param("use SKILL(TEST)", True, id="literal-ignores-case"),
            pytest.param("use Skill(test). now", True, id="literal-then-punctuation"),
            pytest.param("use mySkill(test)", False, id="literal-glued-to-a-word"),
            pytest.param("use a-y-b", False, id="literal-inside-a-hyphenated-word"),
            pytest.param("use x-y- now", False, id="literal-after-a-hyphenated-prefix"),
            pytest.param("use x here", True, id="token"),
            pytest.param("use A:B", True, id="token-ignores-case"),
            pytest.param("call ()", False, id="empty-alias-never-matches"),
            pytest.param("nothing relevant", False, id="no-name"),
        ],
    )
    def test_is_named_in_matches_accepted_names_whole(
        self, entry: agent_brief.SkillKeyword, brief: str, expected: bool
    ) -> None:
        assert entry.is_named_in(brief=brief) is expected

    @pytest.fixture()
    def entry_without_literals(self) -> agent_brief.SkillKeyword:
        return agent_brief.SkillKeyword(skill="a:b", patterns=(), accept=("x",))

    @pytest.mark.parametrize(
        ("brief", "expected"),
        [
            pytest.param("use x here", True, id="token"),
            pytest.param("Skill(test) only", False, id="foreign-literal"),
            pytest.param("unrelated text", False, id="no-name"),
        ],
    )
    def test_entry_without_literals_matches_tokens_only(
        self, entry_without_literals: agent_brief.SkillKeyword, brief: str, expected: bool
    ) -> None:
        assert entry_without_literals.is_named_in(brief=brief) is expected


class TestFindUnnamedSkills:
    def test_longer_skill_name_does_not_name_its_prefix(self) -> None:
        findings = find_unnamed_skills(
            brief="git push the branch, then Skill(dev10x:git-commit)",
            entries=agent_brief.default_entries(),
        )

        assert [finding.skill for finding in findings] == ["dev10x:git"]

    @pytest.mark.parametrize(
        ("brief", "unnamed"),
        [
            pytest.param("via mcp__plugin_dev10x_cli__push_safe", [], id="mcp-qualified"),
            pytest.param("via push_safe", [], id="bare-alias"),
            pytest.param("via push_safe_v2", ["dev10x:git"], id="suffixed"),
            pytest.param("via my_push_safe", ["dev10x:git"], id="snake-prefixed"),
            pytest.param(
                "via mcp__plugin_dev10x_cli__push_safe_v2", ["dev10x:git"], id="mcp-suffixed"
            ),
            pytest.param("via foo__push_safe", ["dev10x:git"], id="double-underscore-prefixed"),
            pytest.param(
                "via mcp__plugin_other_cli__push_safe", ["dev10x:git"], id="other-mcp-server"
            ),
            pytest.param("via `push_safe`.", [], id="punctuated"),
            pytest.param("via PUSH_SAFE", [], id="case-insensitive"),
            pytest.param("via push_safe.", [], id="sentence-final"),
            pytest.param("see src/dev10x/push_safe.py", ["dev10x:git"], id="path-mention"),
            pytest.param("see foo.push_safe", ["dev10x:git"], id="dotted-mention"),
            pytest.param("run ./push_safe", ["dev10x:git"], id="relative-path"),
            pytest.param("see /push_safe", ["dev10x:git"], id="rooted-path"),
            pytest.param(
                "via push_safe/pr_ready", ["dev10x:git"], id="slash-joined-list-over-reports"
            ),
        ],
    )
    def test_alias_counts_only_as_a_whole_name(self, brief: str, unnamed: list[str]) -> None:
        findings = find_unnamed_skills(
            brief=f"git push the branch {brief}", entries=agent_brief.default_entries()
        )

        assert [finding.skill for finding in findings] == unnamed

    @pytest.mark.parametrize(
        ("brief", "unnamed"),
        [
            pytest.param("Run pytest via Skill(test).", [], id="parenthesised-alias"),
            pytest.param("Run pytest via skill(TEST).", [], id="alias-case-insensitive"),
            pytest.param(
                "Run pytest, then test the Skill output.", ["dev10x:py-test"], id="split"
            ),
            pytest.param("Run a skill test with pytest.", ["dev10x:py-test"], id="prose"),
            pytest.param("Run pytest via mySkill(test).", ["dev10x:py-test"], id="prefixed"),
            pytest.param("Run pytest via dev10x:py-test-flaky.", ["dev10x:py-test"], id="longer"),
        ],
    )
    def test_multi_token_alias_matches_only_verbatim(self, brief: str, unnamed: list[str]) -> None:
        findings = find_unnamed_skills(brief=brief, entries=agent_brief.default_entries())

        assert [finding.skill for finding in findings] == unnamed

    def test_reports_each_skill_once(self) -> None:
        findings = find_unnamed_skills(
            brief="git commit, then git commit again, then git push",
            entries=agent_brief.default_entries(),
        )

        assert [finding.skill for finding in findings] == ["dev10x:git-commit", "dev10x:git"]
