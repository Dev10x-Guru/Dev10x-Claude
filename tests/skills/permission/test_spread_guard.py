"""Which rules may travel between checkouts of one repo (GH-1790)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.file_locks import LockTimeoutError
from dev10x.skills.permission.declined_catalog import (
    decline_rules,
    load_declined_rules,
    read_declined_rules,
)
from dev10x.skills.permission.rule_risk import blanket_problem
from dev10x.skills.permission.spread_guard import (
    HeldRule,
    hold_reason,
    hook_denial,
    partition_spreadable,
    render_held,
)

from dev10x.skills.permission import declined_catalog, rule_list_file


class TestBlanketProblem:
    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(bash:*)",
            "Bash(python3:*)",
            "Bash(python3.12:*)",
            "Bash(lua:*)",
            "Bash(curl:*)",
            "Bash(source:*)",
            "Bash(uv run:*)",
            "Bash(gh api:*)",
            "Bash(*)",
            "Bash(rg --pre:*)",
            "Edit(~/.claude/**)",
            "Edit(~/.claude/hooks/**)",
            "Edit(~/**)",
            "Write(//**)",
            "Edit",
            "Read(~/.ssh/**)",
            "Bash(bash -c:*)",
            "Bash(sh -c:*)",
            "Bash(python3 -c:*)",
            "Bash(node -e:*)",
            "Bash(rm -rf:*)",
            "Bash(sudo -n:*)",
            "Bash(sed -i:*)",
            "Bash(timeout 30:*)",
            "Bash(env:*)",
            "Bash(FOO=1 bash:*)",
            "Bash(nice -n 5 sh:*)",
            "Bash(uv run python:*)",
            "Bash(uv run --with x python3 -c:*)",
            "Bash(git push --force:*)",
            "Bash(sort --compress=sh:*)",
            "Read(~/**)",
            "Read(//**)",
            "Read(//home/**)",
            "Edit(~/.claude/plugins/**)",
            "Edit(~/.claude.json)",
            "Edit(~/.claude/memory/../settings.json)",
            "Write(${HOME}/.claude/**)",
            "Write(//home/**)",
        ],
    )
    def test_names_the_blanket_shapes(self, rule: str) -> None:
        assert blanket_problem(rule=rule) is not None

    @pytest.mark.parametrize(
        "rule",
        [
            "Bash(git log:*)",
            "Bash(uv run pytest:*)",
            "Bash(rg:*)",
            "Bash(npm ci:*)",
            "Edit(src/**)",
            "Edit(~/.claude/memory/**)",
            "Edit(~/.claude/projects/**)",
            "Read(~/.claude/**)",
            "Read(//work/**)",
            "Read(src/**)",
            "mcp__plugin_dev10x_cli__pr_get",
            "Bash(python3 scripts/release.py:*)",
            "Bash(git push origin:*)",
            "Bash(timeout 30 pytest:*)",
            "Bash(git:*)",
        ],
    )
    def test_leaves_portable_rules_alone(self, rule: str) -> None:
        assert blanket_problem(rule=rule) is None

    def test_home_variable_spelling_is_a_settings_write(self) -> None:
        assert blanket_problem(rule="Write($HOME/.claude/**)") is not None


@pytest.mark.usefixtures("default_hook_chain")
class TestHookDenial:
    def test_psql_rule_collides_with_the_sql_hook(self) -> None:
        denial = hook_denial(rule="Bash(psql:*)")

        assert denial is not None
        assert denial.startswith("BLOCKED: Direct psql")

    @pytest.mark.parametrize("rule", ["Bash(git log:*)", "Edit(src/**)", "Bash(:*)"])
    def test_no_denial_for_an_allowed_or_non_bash_rule(self, rule: str) -> None:
        assert hook_denial(rule=rule) is None


class TestHoldReason:
    def test_declined_wins_over_everything(self) -> None:
        reason = hold_reason(rule="Bash(git log:*)", declined=frozenset({"Bash(git log:*)"}))

        assert reason == "declined by the supervisor (declined-permissions.yaml)"

    def test_portable_rule_is_not_held(self) -> None:
        assert hold_reason(rule="Bash(git log:*)", declined=frozenset()) is None


class TestPartitionAndRender:
    def test_splits_and_renders(self) -> None:
        spreadable, held = partition_spreadable(
            rules=["Bash(git log:*)", "Bash(bash:*)"], declined=frozenset()
        )

        assert spreadable == ["Bash(git log:*)"]
        assert [item.rule for item in held] == ["Bash(bash:*)"]
        assert render_held(held=held)[:2] == [
            "  held back 1 rule(s) — not copied:",
            "    ! Bash(bash:*)",
        ]

    def test_nothing_held_renders_nothing(self) -> None:
        assert render_held(held=[]) == []

    def test_held_rule_is_a_value(self) -> None:
        assert HeldRule(rule="a", reason="b") == HeldRule(rule="a", reason="b")


class TestDeclinedCatalog:
    @pytest.fixture
    def declined_file(self) -> Path:
        return declined_catalog.declined_path()

    def test_declining_creates_the_file(self, declined_file: Path) -> None:
        result = decline_rules(rules=["Bash(psql:*)", "Bash(psql:*)", "  "])

        assert isinstance(result, SuccessResult)
        assert result.value == {"path": str(declined_file), "added": ["Bash(psql:*)"]}
        assert yaml.safe_load(declined_file.read_text()) == {"declined": ["Bash(psql:*)"]}

    def test_declining_again_adds_nothing(self) -> None:
        decline_rules(rules=["Bash(psql:*)"])

        result = decline_rules(rules=["Bash(psql:*)", "Bash(curl:*)"])

        assert isinstance(result, SuccessResult)
        assert result.value["added"] == ["Bash(curl:*)"]
        assert load_declined_rules() == frozenset({"Bash(psql:*)", "Bash(curl:*)"})

    def test_blank_input_is_refused(self) -> None:
        assert isinstance(decline_rules(rules=[" "]), ErrorResult)

    def test_absent_file_declines_nothing(self) -> None:
        assert load_declined_rules() == frozenset()

    @pytest.mark.parametrize(
        "content",
        ["{not: [yaml", "- a list\n", "declined: nope\n"],
        ids=["unparsable", "not-a-mapping", "no-list"],
    )
    def test_unreadable_file_declines_nothing(self, declined_file: Path, content: str) -> None:
        declined_file.parent.mkdir(parents=True, exist_ok=True)
        declined_file.write_text(content)

        assert load_declined_rules() == frozenset()

    @pytest.mark.parametrize(
        ("content", "message"),
        [("{not: [yaml", "is unreadable"), ("declined: nope\n", "has no `declined:` list")],
        ids=["unparsable", "no-list"],
    )
    def test_read_refuses_a_broken_file(
        self, declined_file: Path, content: str, message: str
    ) -> None:
        declined_file.parent.mkdir(parents=True, exist_ok=True)
        declined_file.write_text(content)

        result = read_declined_rules()

        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_read_treats_an_empty_file_as_nothing_declined(self, declined_file: Path) -> None:
        declined_file.parent.mkdir(parents=True, exist_ok=True)
        declined_file.write_text("")

        assert read_declined_rules() == SuccessResult(value=frozenset())

    def test_non_mapping_file_is_not_overwritten(self, declined_file: Path) -> None:
        declined_file.parent.mkdir(parents=True, exist_ok=True)
        declined_file.write_text("- keep me\n")

        result = decline_rules(rules=["Bash(psql:*)"])

        assert isinstance(result, ErrorResult)
        assert "is not a mapping" in result.error
        assert declined_file.read_text() == "- keep me\n"

    @pytest.mark.parametrize(
        ("error", "message"),
        [(LockTimeoutError("busy"), "please try again"), (OSError("disk full"), "disk full")],
        ids=["lock-timeout", "os-error"],
    )
    def test_write_failure_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
    ) -> None:
        @contextmanager
        def _locked(_path: Path) -> Iterator[dict]:
            raise error
            yield {}

        monkeypatch.setattr(rule_list_file, "locked_yaml_update", _locked)

        result = decline_rules(rules=["Bash(psql:*)"])

        assert isinstance(result, ErrorResult)
        assert message in result.error
