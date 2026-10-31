from __future__ import annotations

from typing import Any

from dev10x.ci_review.report import elide_prompt, summarize

_ENTRIES: list[dict[str, Any]] = [
    {"kind": "inline_comment", "path": "a.py", "line": 3, "body": "**HIGH** bug\nmore"},
    {"kind": "inline_comment", "path": "b.py", "startLine": 9, "body": ""},
    {"kind": "gh", "argv": ["gh", "pr", "review", "1"], "stdin": "x " * 200},
    {"kind": "gh", "argv": ["gh", "pr", "merge", "1"]},
    {"kind": "post_step", "step": "Convert", "branch": "draft", "argv": ["gh", "pr", "ready"]},
    {"kind": "post_step", "step": "Post", "branch": "nothing-to-post"},
]


def test_summary_groups_entries_by_kind() -> None:
    text = summarize(
        workflow="code-review",
        failed_guards=["draft"],
        cli_version="2.1.0",
        usage="### Claude usage\n",
        entries=_ENTRIES,
    )

    assert "- Guards: draft" in text
    assert "- Claude CLI: 2.1.0" in text
    assert "#### inline_comment (2)" in text
    assert "- a.py:3 — **HIGH** bug" in text
    assert "- b.py:9 — \n" in text
    assert "- `gh pr review 1` — " + "x " * 79 + "x…" in text
    assert "- `gh pr merge 1`\n" in text
    assert "- Convert: draft → `gh pr ready`" in text
    assert "- Post: nothing-to-post\n" in text


def test_empty_summary() -> None:
    text = summarize(workflow="hygiene", failed_guards=[], cli_version="1", usage="u", entries=[])

    assert "- Guards: all pass" in text
    assert "- (empty)" in text


def test_short_body_is_not_truncated() -> None:
    text = summarize(
        workflow="w",
        failed_guards=[],
        cli_version="1",
        usage="u",
        entries=[{"kind": "gh", "argv": ["gh"], "body_file_content": "short"}],
    )

    assert "- `gh` — short" in text


def test_elide_prompt() -> None:
    prompt = "first\nmiddle\nlast"

    assert elide_prompt(argv=["claude", "-p", prompt, "--x"], prompt=prompt) == [
        "claude",
        "-p",
        "first … last (17 bytes)",
        "--x",
    ]
