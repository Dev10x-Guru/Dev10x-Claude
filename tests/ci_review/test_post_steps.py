from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dev10x.ci_review.outbox import append_entry, read_entries
from dev10x.ci_review.post_steps import (
    DRAFT_STEP,
    HYGIENE_BODY,
    PROBE_PATTERN,
    PROBE_STEP,
    code_review_post_steps,
    hygiene_post_step,
    is_probe,
)
from dev10x.core.domain.common.result import ErrorResult, SuccessResult

_WORKFLOW: Path = Path(__file__).parents[2] / ".github" / "workflows" / "claude-code-review.yml"


def test_probe_pattern_matches_the_workflow() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    (jq_pattern,) = re.findall(r'test\("(.*?)"; "i"\)', text)

    assert jq_pattern.replace("\\\\", "\\") == PROBE_PATTERN


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Test comment", True),
        ("testing if I can comment here.", True),
        ("Can I post here?", True),
        ("  this is a test  ", True),
        ("checking whether the inline comment tool works!", True),
        ("Test comment **bold**", False),
        ("Test that the parser handles empty input", False),
        ("test " * 30, False),
    ],
)
def test_is_probe(body: str, expected: bool) -> None:
    assert is_probe(body=body) is expected


def _inline(*, outbox: Path, comment_id: int, body: str) -> None:
    append_entry(
        path=outbox,
        entry={"kind": "inline_comment", "comment_id": comment_id, "path": "a.py", "body": body},
    )


class TestCodeReview:
    @pytest.fixture
    def outbox(self, tmp_path: Path) -> Path:
        return tmp_path / "outbox.jsonl"

    def test_findings_draft_the_pr(self, outbox: Path) -> None:
        _inline(outbox=outbox, comment_id=1, body="Test comment")
        _inline(outbox=outbox, comment_id=2, body="**HIGH** SQL injection")

        recorded = code_review_post_steps(outbox=outbox, repo="o/r", pr=5)

        assert [(entry["step"], entry["branch"]) for entry in recorded] == [
            (PROBE_STEP, "delete"),
            (DRAFT_STEP, "draft"),
        ]
        assert recorded[0]["argv"][-1] == "repos/o/r/pulls/comments/1"
        assert recorded[1]["argv"] == ["gh", "pr", "ready", "5", "--undo", "--repo", "o/r"]
        assert recorded[1]["findings"] == 1

    def test_only_probes_keep_the_pr_ready(self, outbox: Path) -> None:
        _inline(outbox=outbox, comment_id=1, body="Can I post here?")

        recorded = code_review_post_steps(outbox=outbox, repo="o/r", pr=5)

        assert recorded[-1]["branch"] == "stay-ready"
        assert [entry["kind"] for entry in read_entries(path=outbox)] == [
            "inline_comment",
            "post_step",
            "post_step",
        ]

    def test_empty_outbox(self, outbox: Path) -> None:
        recorded = code_review_post_steps(outbox=outbox, repo="o/r", pr=5)

        assert [entry["branch"] for entry in recorded] == ["stay-ready"]


class TestHygiene:
    @pytest.fixture
    def checkout(self, tmp_path: Path) -> Path:
        (tmp_path / ".claude-ci").mkdir()
        return tmp_path

    @pytest.fixture
    def outbox(self, tmp_path: Path) -> Path:
        return tmp_path / "outbox.jsonl"

    def _post(self, *, checkout: Path, outbox: Path, prior: int | None) -> dict[str, Any]:
        result = hygiene_post_step(
            checkout=checkout, outbox=outbox, repo="o/r", pr=3, prior_comment_id=prior
        )
        assert isinstance(result, SuccessResult), result
        return result.value

    @pytest.mark.parametrize(
        "arrange",
        [
            lambda body: None,
            lambda body: body.write_text("", encoding="utf-8"),
            lambda body: body.symlink_to(body.parent / "elsewhere"),
        ],
        ids=["missing", "empty", "symlink"],
    )
    def test_no_body_is_an_error(
        self, checkout: Path, outbox: Path, arrange: Callable[[Path], object]
    ) -> None:
        arrange(checkout / HYGIENE_BODY)

        result = hygiene_post_step(
            checkout=checkout, outbox=outbox, repo="o/r", pr=3, prior_comment_id=None
        )

        assert isinstance(result, ErrorResult)
        assert read_entries(path=outbox)[0]["branch"] == "error"

    def test_prior_comment_is_updated(self, checkout: Path, outbox: Path) -> None:
        (checkout / HYGIENE_BODY).write_text("✅ PR hygiene checks pass.\n", encoding="utf-8")

        entry = self._post(checkout=checkout, outbox=outbox, prior=77)

        assert entry["branch"] == "update"
        assert "repos/o/r/issues/comments/77" in entry["argv"]
        assert entry["body"].endswith("\n<!-- dev10x-pr-hygiene -->\n")

    def test_pass_without_prior_posts_nothing(self, checkout: Path, outbox: Path) -> None:
        (checkout / HYGIENE_BODY).write_text(
            "Summary\n✅ PR hygiene checks pass.\n", encoding="utf-8"
        )

        entry = self._post(checkout=checkout, outbox=outbox, prior=None)

        assert entry["branch"] == "nothing-to-post"
        assert "argv" not in entry

    def test_findings_without_prior_comment(self, checkout: Path, outbox: Path) -> None:
        (checkout / HYGIENE_BODY).write_text("❌ Title is too long\n", encoding="utf-8")

        entry = self._post(checkout=checkout, outbox=outbox, prior=None)

        assert entry["branch"] == "comment"
        assert entry["argv"][:4] == ["gh", "pr", "comment", "3"]
