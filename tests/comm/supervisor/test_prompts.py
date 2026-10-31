"""Tests for reading a numbered prompt off a pane's visible screen (GH-1692)."""

from __future__ import annotations

import pytest

from dev10x.comm.supervisor.prompts import Prompt, PromptOption, find_option, parse_prompt

PERMISSION = """\
● Writing hello.txt

────────────────────────────────────────
 Bash command
 Register the relay mailbox on the bus
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 │ send.py registry hello
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 This command requires approval

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don’t ask again for:
      /work/skills/bus/scripts/send.py registry *
   3. No

 Esc to cancel · Tab to amend
"""

WIDGET = """\
Earlier the plan listed:
1. Parse
2. Gather

 ☐ Keys test

Which session should I test?

❯ 1. Pressed it on the page (Recommended)
     I'll confirm that actions.jsonl logged the key.
  2. You send it via /keys
     I POST /keys myself.
  3. Type something.
"""


class TestParsePrompt:
    def test_permission_prompt(self) -> None:
        assert parse_prompt(pane_text=PERMISSION) == Prompt(
            question="Do you want to proceed?",
            options=[
                PromptOption(key="1", label="Yes", selected=True),
                PromptOption(
                    key="2",
                    label="Yes, and don’t ask again for:",
                    detail="/work/skills/bus/scripts/send.py registry *",
                ),
                PromptOption(key="3", label="No"),
            ],
        )

    def test_widget_takes_the_last_list(self) -> None:
        prompt = parse_prompt(pane_text=WIDGET)

        assert prompt is not None
        assert (prompt.question, [option.label for option in prompt.options]) == (
            "Which session should I test?",
            ["Pressed it on the page (Recommended)", "You send it via /keys", "Type something."],
        )

    def test_widget_option_detail(self) -> None:
        prompt = parse_prompt(pane_text=WIDGET)

        assert prompt is not None
        assert prompt.options[0].detail == "I'll confirm that actions.jsonl logged the key."

    @pytest.mark.parametrize(
        "text",
        ["", "just output\n", "1. only one option\n", "2. starts at two\n3. three\n"],
        ids=["empty", "no-list", "single", "no-first"],
    )
    def test_no_prompt(self, text: str) -> None:
        assert parse_prompt(pane_text=text) is None

    def test_gap_ends_the_run(self) -> None:
        prompt = parse_prompt(pane_text="1. a\n2. b\n4. d\n")

        assert prompt is not None
        assert [option.key for option in prompt.options] == ["1", "2"]

    def test_question_skips_rule_lines(self) -> None:
        prompt = parse_prompt(pane_text="Pick one\n────────────\n1. a\n2. b\n")

        assert prompt is not None
        assert prompt.question == "Pick one"

    def test_no_question_above(self) -> None:
        prompt = parse_prompt(pane_text="────────────\n1. a\n2. b\n")

        assert prompt is not None
        assert prompt.question == ""


class TestFindOption:
    @pytest.fixture
    def prompt(self) -> Prompt | None:
        return parse_prompt(pane_text=PERMISSION)

    def test_matches_key_and_label(self, prompt: Prompt | None) -> None:
        assert find_option(prompt=prompt, key="3", label="No") == PromptOption(key="3", label="No")

    @pytest.mark.parametrize(
        ("key", "label"),
        [("3", "Yes"), ("9", "No")],
        ids=["label-changed", "key-gone"],
    )
    def test_refuses_a_changed_prompt(self, prompt: Prompt | None, key: str, label: str) -> None:
        assert find_option(prompt=prompt, key=key, label=label) is None

    def test_no_prompt(self) -> None:
        assert find_option(prompt=None, key="1", label="Yes") is None
