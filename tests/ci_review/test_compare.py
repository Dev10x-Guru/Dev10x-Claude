from __future__ import annotations

import json
from typing import Any

import pytest

from dev10x.ci_review import compare
from dev10x.ci_review.compare import (
    NO_SEVERITY,
    CiPosted,
    ComparisonRow,
    Finding,
    fetch_ci_posted,
    local_findings,
    local_verdict,
    severity_of,
)
from dev10x.core.domain.common.result import ErrorResult, Result, SuccessResult, err, ok

_RUN: str = "repos/o/r/actions/runs/42"
_COMMENTS: str = "repos/o/r/pulls/5/comments"
_REVIEWS: str = "repos/o/r/pulls/5/reviews"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("**CRITICAL**: SQL injection", "CRITICAL"),
        ("[WARNING] slow loop", "WARNING"),
        ("INFO: naming", "INFO"),
        ("No label here, warnings aside", NO_SEVERITY),
    ],
)
def test_severity_of(body: str, expected: str) -> None:
    assert severity_of(body=body) == expected


def test_local_findings_skip_probes_and_read_start_line() -> None:
    entries: list[dict[str, Any]] = [
        {"kind": "inline_comment", "path": "b.py", "startLine": 9, "body": "WARNING x"},
        {"kind": "inline_comment", "path": "a.py", "line": 3, "body": "CRITICAL y"},
        {"kind": "inline_comment", "path": "a.py", "line": 1, "body": "Test comment"},
        {"kind": "gh", "argv": ["gh", "pr", "review"]},
    ]

    assert local_findings(entries=entries) == [
        Finding(path="a.py", line=3, severity="CRITICAL"),
        Finding(path="b.py", line=9, severity="WARNING"),
    ]


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([], None),
        ([{"kind": "gh", "argv": ["gh", "pr", "comment", "5"]}], None),
        (
            [{"kind": "gh", "argv": ["gh", "pr", "review", "5", "--request-changes"]}],
            "CHANGES_REQUESTED",
        ),
        ([{"kind": "gh", "argv": ["gh", "pr", "review", "5", "-a"]}], "APPROVED"),
        ([{"kind": "gh", "argv": ["gh", "pr", "review", "5"]}], "COMMENTED"),
        (
            [
                {"kind": "gh", "argv": ["gh", "pr", "review", "5", "--approve"]},
                {"kind": "gh", "argv": ["gh", "pr", "review", "5", "--comment"]},
            ],
            "COMMENTED",
        ),
    ],
    ids=["none", "not-a-review", "request-changes", "short-approve", "no-flag", "last-wins"],
)
def test_local_verdict(entries: list[dict[str, Any]], expected: str | None) -> None:
    assert local_verdict(entries=entries) == expected


def test_compare_pairs_findings_by_path_and_line() -> None:
    entries: list[dict[str, Any]] = [
        {"kind": "inline_comment", "path": "a.py", "line": 3, "body": "CRITICAL y"},
        {"kind": "inline_comment", "path": "b.py", "line": 9, "body": "WARNING x"},
        {"kind": "gh", "argv": ["gh", "pr", "review", "5", "--request-changes"]},
    ]
    ci = CiPosted(
        run_id=42,
        findings=[
            Finding(path="a.py", line=3, severity="WARNING"),
            Finding(path="c.py", line=1, severity="CRITICAL"),
        ],
        verdicts=["CHANGES_REQUESTED"],
    )

    result = compare.compare(entries=entries, ci=ci)

    assert result.rows == [
        ComparisonRow(path="a.py", line=3, local="CRITICAL", ci="WARNING"),
        ComparisonRow(path="b.py", line=9, local="WARNING", ci=None),
        ComparisonRow(path="c.py", line=1, local=None, ci="CRITICAL"),
    ]
    assert result.local_verdict == "CHANGES_REQUESTED"


def _lines(*items: dict[str, Any]) -> str:
    return "".join(json.dumps(item) + "\n" for item in items)


_IN_RUN: str = "2026-10-31T12:05:00Z"
_BEFORE: str = "2026-10-31T11:00:00Z"
_HEAD: str = "head1"
_OTHER: str = "other1"


def _comment(**fields: Any) -> dict[str, Any]:
    return {
        "path": "a.py",
        "line": 3,
        "body": "WARNING",
        "created_at": _IN_RUN,
        "commit": _HEAD,
        "bot": True,
        **fields,
    }


def _review(**fields: Any) -> dict[str, Any]:
    return {
        "state": "CHANGES_REQUESTED",
        "submitted_at": _IN_RUN,
        "commit": _HEAD,
        "bot": True,
        **fields,
    }


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Result[str]]:
    replies: dict[str, Result[str]] = {
        _RUN: ok(
            json.dumps(
                {
                    "head_sha": _HEAD,
                    "run_started_at": "2026-10-31T12:00:00Z",
                    "updated_at": "2026-10-31T12:10:00Z",
                }
            )
        ),
        _COMMENTS: ok(
            _lines(
                _comment(),
                _comment(path="old.py", line=1, body="x", created_at=_BEFORE),
                _comment(path="me.py", line=2, body="x", bot=False),
                _comment(path="z.py", line=None, body=None, created_at=None),
            )
        ),
        _REVIEWS: ok(
            _lines(
                _review(),
                _review(state="APPROVED", submitted_at=_BEFORE),
            )
        ),
    }

    def fake_run(*, args: list[str], timeout: float) -> Result[str]:
        url = next(arg for arg in args if arg.startswith("repos/"))
        return replies[url]

    monkeypatch.setattr(compare, "run_checked", fake_run)
    return replies


def test_fetch_keeps_only_bot_posts_inside_the_run(answers: dict[str, Result[str]]) -> None:
    result = fetch_ci_posted(repo="o/r", pr=5, run_id=42)

    assert result == SuccessResult(
        value=CiPosted(
            run_id=42,
            findings=[Finding(path="a.py", line=3, severity="WARNING")],
            verdicts=["CHANGES_REQUESTED"],
        )
    )


class TestHeadCommitAttribution:
    @pytest.fixture
    def result(self, answers: dict[str, Result[str]]) -> Result[CiPosted]:
        answers[_COMMENTS] = ok(
            _lines(_comment(), _comment(path="cov.py", line=8, body="INFO", commit=_OTHER))
        )
        answers[_REVIEWS] = ok(_lines(_review(), _review(state="APPROVED", commit=_OTHER)))
        return fetch_ci_posted(repo="o/r", pr=5, run_id=42)

    def test_excludes_bot_comments_on_another_commit(self, result: Result[CiPosted]) -> None:
        assert isinstance(result, SuccessResult)
        assert result.value.findings == [Finding(path="a.py", line=3, severity="WARNING")]

    def test_excludes_bot_reviews_on_another_commit(self, result: Result[CiPosted]) -> None:
        assert isinstance(result, SuccessResult)
        assert result.value.verdicts == ["CHANGES_REQUESTED"]


@pytest.mark.parametrize(
    ("url", "reply", "message"),
    [
        (_RUN, err("not found"), "not found"),
        (_RUN, ok("nope"), "invalid JSON"),
        (_RUN, ok("{}"), "no usable start/end time"),
        (_COMMENTS, err("comments broke"), "comments broke"),
        (_COMMENTS, ok("{bad\n"), "invalid JSON"),
        (_REVIEWS, err("reviews broke"), "reviews broke"),
    ],
    ids=["run-error", "run-json", "run-times", "comments-error", "comments-json", "reviews"],
)
def test_fetch_failures(
    answers: dict[str, Result[str]], url: str, reply: Result[str], message: str
) -> None:
    answers[url] = reply

    result = fetch_ci_posted(repo="o/r", pr=5, run_id=42)

    assert isinstance(result, ErrorResult)
    assert message in result.error


@pytest.mark.parametrize(
    ("url", "item"),
    [
        (_COMMENTS, _comment(line="three")),
        (_COMMENTS, _comment(line=[3])),
        (_COMMENTS, _comment(created_at="yesterday")),
        (_COMMENTS, _comment(created_at="2026-10-31T12:05:00")),
        (_REVIEWS, _review(submitted_at=1730376300)),
    ],
    ids=["line-text", "line-list", "stamp-text", "stamp-naive", "stamp-number"],
)
def test_fetch_reports_malformed_posts(
    answers: dict[str, Result[str]], url: str, item: dict[str, Any]
) -> None:
    answers[url] = ok(_lines(item))

    result = fetch_ci_posted(repo="o/r", pr=5, run_id=42)

    assert isinstance(result, ErrorResult)
    assert "posted a comment or review that cannot be read" in result.error
