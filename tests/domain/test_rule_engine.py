from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.rule_engine import RuleEngine
from dev10x.domain.validation_rule import Compensation, Config, Rule


class TestRuleFromYamlEntry:
    @pytest.fixture()
    def entry(self) -> dict:
        return {
            "name": "block-env",
            "matcher": "Edit|Write",
            "hook_block": True,
            "file_names": [".env"],
            "message": "Blocked: {file_path}",
            "compensations": [
                {"type": "use-skill", "skill": "Dev10x:edit", "guardrails": "safety"}
            ],
        }

    def test_creates_rule_with_all_fields(self, entry: dict) -> None:
        rule = Rule.from_yaml_entry(entry=entry)

        assert rule.name == "block-env"
        assert rule.matcher == "Edit|Write"
        assert rule.hook_block is True
        assert rule.file_names == [".env"]

    def test_parses_compensations(self, entry: dict) -> None:
        rule = Rule.from_yaml_entry(entry=entry)

        assert len(rule.compensations) == 1
        assert rule.compensations[0].skill == "Dev10x:edit"

    def test_defaults_for_missing_fields(self) -> None:
        rule = Rule.from_yaml_entry(entry={"name": "minimal"})

        assert rule.matcher == "Bash"
        assert rule.hook_block is True
        assert rule.patterns == []
        assert rule.compensations == []


class TestCompensationFromYamlEntry:
    def test_filters_unknown_keys(self) -> None:
        entry = {"type": "use-skill", "skill": "foo", "unknown_key": "bar"}

        comp = Compensation.from_yaml_entry(entry=entry)

        assert comp.type == "use-skill"
        assert comp.skill == "foo"


class TestRuleEngineFromYaml:
    @pytest.fixture()
    def yaml_path(self, tmp_path: Path) -> Path:
        content = {
            "rules": [
                {
                    "name": "block-env",
                    "matcher": "Edit|Write",
                    "hook_block": True,
                    "file_names": [".env"],
                    "message": "BLOCKED",
                },
                {
                    "name": "block-push",
                    "matcher": "Bash",
                    "hook_block": True,
                    "patterns": ["^git push"],
                    "compensations": [{"type": "use-skill", "skill": "Dev10x:git"}],
                },
                {
                    "name": "advisory-only",
                    "matcher": "Bash",
                    "hook_block": False,
                    "patterns": ["^echo"],
                },
            ]
        }
        path = tmp_path / "rules.yaml"
        path.write_text(yaml.dump(content))
        return path

    def test_splits_edit_and_command_rules(self, yaml_path: Path) -> None:
        engine = RuleEngine.from_yaml(path=yaml_path)

        assert len(engine.edit_rules) == 1
        assert len(engine.command_rules) == 1

    def test_skips_non_blocking_rules(self, yaml_path: Path) -> None:
        engine = RuleEngine.from_yaml(path=yaml_path)

        all_names = {r.name for r in engine.edit_rules + engine.command_rules}
        assert "advisory-only" not in all_names

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(": invalid: yaml: [")

        with pytest.raises(yaml.YAMLError):
            RuleEngine.from_yaml(path=path)


class TestRuleEngineFromConfig:
    def test_filters_by_hook_block(self) -> None:
        config = Config(
            rules=[
                Rule(name="active", hook_block=True, matcher="Bash", patterns=["^git"]),
                Rule(name="inactive", hook_block=False, matcher="Bash"),
            ]
        )

        engine = RuleEngine.from_config(config=config)

        assert len(engine.command_rules) == 1
        assert engine.command_rules[0].name == "active"


class TestRuleEngineEvaluate:
    @pytest.fixture()
    def engine(self) -> RuleEngine:
        return RuleEngine(
            edit_rules=[
                Rule(
                    name="block-env",
                    matcher="Edit|Write",
                    file_names=[".env"],
                    message="BLOCKED: {file_path}",
                ),
                Rule(
                    name="block-secrets",
                    matcher="Edit|Write",
                    file_pattern=r".*\.secret$",
                    content_pattern=r"password",
                    message="Secret content blocked",
                ),
            ],
        )

    def test_matches_by_file_name(self, engine: RuleEngine) -> None:
        result = engine.evaluate(file_path="/app/.env", content="KEY=val")

        assert result is not None
        assert result.rule_name == "block-env"

    def test_returns_none_for_unmatched_file(self, engine: RuleEngine) -> None:
        result = engine.evaluate(file_path="/app/main.py", content="x = 1")

        assert result is None

    def test_matches_file_and_content_pattern(self, engine: RuleEngine) -> None:
        result = engine.evaluate(file_path="db.secret", content="password=abc")

        assert result is not None
        assert result.rule_name == "block-secrets"

    def test_skips_when_content_doesnt_match(self, engine: RuleEngine) -> None:
        result = engine.evaluate(file_path="db.secret", content="host=localhost")

        assert result is None

    def test_returns_first_match(self, engine: RuleEngine) -> None:
        result = engine.evaluate(file_path=".env", content="password=abc")

        assert result is not None
        assert result.rule_name == "block-env"


class TestRuleEngineEvaluateFile:
    def test_matches_by_file_only(self) -> None:
        engine = RuleEngine(
            edit_rules=[
                Rule(
                    name="block-env", matcher="Edit|Write", file_names=[".env"], message="BLOCKED"
                ),
            ],
        )

        result = engine.evaluate_file(file_path="/app/.env")

        assert result is not None
        assert result.rule_name == "block-env"

    def test_returns_none_for_unmatched(self) -> None:
        engine = RuleEngine(
            edit_rules=[
                Rule(
                    name="block-env", matcher="Edit|Write", file_names=[".env"], message="BLOCKED"
                ),
            ],
        )

        result = engine.evaluate_file(file_path="/app/main.py")

        assert result is None


class TestRuleEngineEvaluateCommand:
    @pytest.fixture()
    def engine(self) -> RuleEngine:
        return RuleEngine(
            command_rules=[
                Rule(
                    name="block-push",
                    matcher="Bash",
                    patterns=["^git push"],
                    except_=["--dry-run"],
                    compensations=[Compensation(type="use-skill", skill="Dev10x:git")],
                ),
            ],
        )

    def test_matches_command(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="git push origin main")

        assert result is not None
        assert result.name == "block-push"

    def test_returns_none_for_unmatched(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="git status")

        assert result is None

    def test_respects_except_patterns(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="git push --dry-run")

        assert result is None


class TestSubcommandBoundary:
    """Regression coverage for GH-84: `git commit` matching `git commit-msg`."""

    @pytest.fixture()
    def engine(self) -> RuleEngine:
        return RuleEngine(
            command_rules=[
                Rule(
                    name="git-commit",
                    matcher="Bash",
                    patterns=["git commit"],
                    compensations=[Compensation(type="use-skill", skill="Dev10x:git-commit")],
                ),
                Rule(
                    name="gh-pr-create",
                    matcher="Bash",
                    patterns=["gh pr create"],
                    compensations=[Compensation(type="use-skill", skill="Dev10x:gh-pr-create")],
                ),
            ],
        )

    def test_real_git_commit_still_blocked(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="git commit -m 'msg'")

        assert result is not None
        assert result.name == "git-commit"

    def test_git_commit_msg_argument_passes(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(
            command="/tmp/Dev10x/bin/mktmp.sh git commit-msg .txt",
        )

        assert result is None

    def test_git_commits_word_extension_passes(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="echo git commits today")

        assert result is None

    def test_gh_pr_create_real_invocation_blocked(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="gh pr create --draft")

        assert result is not None
        assert result.name == "gh-pr-create"

    def test_gh_pr_create_hyphenated_argument_passes(self, engine: RuleEngine) -> None:
        result = engine.evaluate_command(command="echo gh pr create-something")

        assert result is None
