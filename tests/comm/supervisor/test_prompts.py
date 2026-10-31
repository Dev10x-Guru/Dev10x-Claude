"""Tests for reading a numbered prompt off a pane's visible screen (GH-1692)."""

from __future__ import annotations

import pytest

from dev10x.comm.supervisor.prompts import (
    Prompt,
    PromptOption,
    find_option,
    parse_prompt,
    parse_status_line,
    parse_status_line_ansi,
    strip_ansi,
)

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


RULE = "─" * 40
IDLE_PANE = (
    "✻ Sautéed for 59s\n"
    f"{RULE}\n"
    "❯ \n"
    f"{RULE}\n"
    "   wt poc   janusz/GH-1692/poc  GH-1692  PR#1718  Opus 5.5\n"
    "  ⏵⏵ accept edits on (shift+tab to cycle)\n"
)


class TestParseStatusLine:
    def test_reads_the_bar_under_the_input_box(self) -> None:
        assert parse_status_line(pane_text=IDLE_PANE) == (
            "wt poc   janusz/GH-1692/poc  GH-1692  PR#1718  Opus 5.5"
        )

    def test_keeps_every_bar_line_and_drops_hints(self) -> None:
        text = f"{RULE}\n❯ draft\nmore draft\n{RULE}\n  ctx 40%\n\n  main\n  ? for shortcuts\n"

        assert parse_status_line(pane_text=text) == "ctx 40%\nmain"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "just output\n",
            f"{RULE}\n❯ 1. Yes\n  2. No\n{RULE}\n  bar\n",
            f"{RULE}\nDo you want to proceed?\n{RULE}\n  bar\n",
            f"{RULE}\n{RULE}\n  bar\n",
        ],
        ids=["empty", "no-rules", "option-list", "dialog", "adjacent-rules"],
    )
    def test_no_input_box_means_no_bar(self, text: str) -> None:
        assert parse_status_line(pane_text=text) == ""


GREY = "\x1b[0m\x1b[38;2;136;136;136m"
SEGMENT = "\x1b[38;2;251;241;199m\x1b[48;2;177;98;134m wt poc \x1b[0m"
COLOURED_PANE = (
    f"{GREY}{RULE}\x1b[0m\n❯ \n{GREY}{RULE}\x1b[0m\n"
    f"  {SEGMENT}\n  \x1b[38;2;175;135;255m⏵⏵ accept edits on\x1b[0m\n"
)


class TestColouredStatusLine:
    def test_keeps_the_escape_codes_of_the_bar_rows(self) -> None:
        assert parse_status_line_ansi(pane_ansi=COLOURED_PANE) == SEGMENT

    def test_plain_parse_ignores_the_codes(self) -> None:
        assert parse_status_line(pane_text=COLOURED_PANE) == "wt poc"

    def test_no_bar(self) -> None:
        assert parse_status_line_ansi(pane_ansi="plain output\n") == ""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("\x1b[1;31mred\x1b[0m", "red"),
            ("\x1b]8;;https://x.dev\x07link\x1b]8;;\x07", "link"),
            ("\x1b[?25lhidden cursor", "hidden cursor"),
            ("no codes", "no codes"),
        ],
        ids=["sgr", "osc-link", "private-mode", "plain"],
    )
    def test_strip_ansi(self, text: str, expected: str) -> None:
        assert strip_ansi(text) == expected
