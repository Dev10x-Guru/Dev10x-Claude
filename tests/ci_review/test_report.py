from __future__ import annotations

from typing import Any

import pytest

from dev10x.ci_review.compare import CiPosted, Comparison, ComparisonRow
from dev10x.ci_review.report import (
    LOCAL_REPLICA_HEADER,
    LOCAL_REPLICA_MARKER,
    elide_prompt,
    render_comparison,
    replica_body,
    summarize,
)

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


class TestComparison:
    def test_renders_a_row_per_finding(self) -> None:
        comparison = Comparison(
            rows=[
                ComparisonRow(path="a.py", line=3, local="CRITICAL", ci="WARNING"),
                ComparisonRow(path="b.py", line=9, local="WARNING", ci=None),
                ComparisonRow(path="c.py", line=1, local=None, ci="CRITICAL"),
            ],
            local_verdict="CHANGES_REQUESTED",
            ci=CiPosted(run_id=42, findings=[], verdicts=["CHANGES_REQUESTED"]),
        )

        text = render_comparison(comparison=comparison)

        assert text == (
            "### Compared with CI run 42\n\n"
            "| Finding | Local | CI |\n"
            "| --- | --- | --- |\n"
            "| `a.py:3` | CRITICAL | WARNING |\n"
            "| `b.py:9` | WARNING | absent |\n"
            "| `c.py:1` | absent | CRITICAL |\n\n"
            "- Matched: 1 · local only: 1 · CI only: 1\n"
            "- Verdict: local CHANGES_REQUESTED · CI CHANGES_REQUESTED\n"
        )

    def test_empty_comparison(self) -> None:
        comparison = Comparison(
            rows=[], local_verdict=None, ci=CiPosted(run_id=1, findings=[], verdicts=[])
        )

        text = render_comparison(comparison=comparison)

        assert "| (no inline findings on either side) | | |" in text
        assert "- Verdict: local — · CI —" in text


class TestReplicaBody:
    @pytest.fixture
    def body(self) -> str:
        return replica_body(
            workflow="code-review",
            report="## dev10x ci-review — code-review\n<!-- dev10x-pr-hygiene -->\n",
            entries=[
                {
                    "kind": "gh",
                    "argv": ["gh", "pr", "review", "5", "--approve"],
                    "body_file_content": "## Review Summary (Round 3)\nAll good",
                },
                {"kind": "post_step", "step": "Post hygiene comment", "body": "❌ Title"},
                {"kind": "post_step", "step": "Convert", "branch": "draft"},
                {"kind": "inline_comment", "path": "a.py", "line": 1, "body": "x"},
            ],
        )

    def test_starts_with_the_replica_header(self, body: str) -> None:
        assert body.startswith(f"## {LOCAL_REPLICA_HEADER} — code-review\n")

    def test_ends_with_the_local_marker(self, body: str) -> None:
        assert body.endswith(f"\n{LOCAL_REPLICA_MARKER}\n")

    def test_drops_ci_markers(self, body: str) -> None:
        assert "dev10x-pr-hygiene" not in body

    def test_cannot_be_read_as_a_ci_round(self, body: str) -> None:
        assert "(Round 3)" not in body
        assert "(replica of round 3)" in body

    def test_includes_each_would_be_summary(self, body: str) -> None:
        assert body.count("<details><summary>Summary the replay would have posted") == 2
        assert "❌ Title" in body


def test_elide_prompt() -> None:
    prompt = "first\nmiddle\nlast"

    assert elide_prompt(argv=["claude", "-p", prompt, "--x"], prompt=prompt) == [
        "claude",
        "-p",
        "first … last (17 bytes)",
        "--x",
    ]
