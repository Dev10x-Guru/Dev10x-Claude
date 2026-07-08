"""Regression tests for the top-level-comment detection jq filter.

GH-764 F1: the HTML marker was placed in the blocking-signal predicate
instead of the identity predicate, which (1) still missed third-party
reviewers posting under a generic CI account and (2) turned marker-tagged
bot walkthroughs into false merge blockers. The jq lives in a sibling
file so it is testable in isolation — a jq string-literal escape or
predicate-placement bug is invisible to shellcheck.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FILTER = Path(__file__).parents[3] / "skills" / "gh-pr-merge" / "scripts" / "top-level-comments.jq"

# Mixed surface: a generic-CI-account reviewer (id 1) self-identifies only
# via an HTML marker; a bot walkthrough (id 2) is marker-tagged but carries
# no blocking keyword; id 3 is a plain bot blocking finding; id 4 is a human;
# ids 5/6 are reviews differing only by state.
FIXTURE = [
    {
        "id": 1,
        "user": {"login": "ci-runner", "type": "User"},
        "body": "<!-- coderabbit -->\nREQUIRED: fix X",
    },
    {
        "id": 2,
        "user": {"login": "some-bot", "type": "Bot"},
        "body": "<!-- walkthrough -->\nLGTM, nice work",
    },
    {"id": 3, "user": {"login": "claude", "type": "Bot"}, "body": "BLOCKING: null deref"},
    {"id": 4, "user": {"login": "alice", "type": "User"}, "body": "CRITICAL: please fix"},
    {
        "id": 5,
        "user": {"login": "rev-bot", "type": "Bot"},
        "body": "REQUIRED: draft note",
        "state": "PENDING",
    },
    {
        "id": 6,
        "user": {"login": "rev-bot", "type": "Bot"},
        "body": "REQUIRED: real issue",
        "state": "CHANGES_REQUESTED",
    },
]

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not on PATH")


def _run_filter(rows: list[dict], src: str, tmp_path: Path) -> list[dict]:
    fixture = tmp_path / "rows.json"
    fixture.write_text(json.dumps(rows))
    result = subprocess.run(
        ["jq", "-f", str(FILTER), "--arg", "src", src, str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_filter_compiles_and_selects_expected_ids(tmp_path: Path) -> None:
    selected = _run_filter(FIXTURE, "comment", tmp_path)
    assert {row["id"] for row in selected} == {1, 3, 6}


def test_generic_ci_account_marker_is_identity_not_signal(tmp_path: Path) -> None:
    # GH-764 F1 (1): a User-type account outside BOT_LOGIN is still
    # inspected via its HTML marker, and selected because it carries a
    # blocking keyword.
    selected = _run_filter([FIXTURE[0]], "comment", tmp_path)
    assert [row["id"] for row in selected] == [1]


def test_marker_walkthrough_without_keyword_not_flagged(tmp_path: Path) -> None:
    # GH-764 F1 (2): a marker-tagged bot post with no blocking keyword is
    # NOT a merge blocker.
    assert _run_filter([FIXTURE[1]], "comment", tmp_path) == []


def test_human_comment_not_flagged(tmp_path: Path) -> None:
    assert _run_filter([FIXTURE[3]], "comment", tmp_path) == []


@pytest.mark.parametrize(
    ("state", "expected"),
    [("PENDING", []), ("DISMISSED", []), ("CHANGES_REQUESTED", [6]), ("COMMENTED", [6])],
)
def test_review_state_guard(state: str, expected: list[int], tmp_path: Path) -> None:
    row = {**FIXTURE[5], "state": state}
    selected = _run_filter([row], "review", tmp_path)
    assert [r["id"] for r in selected] == expected


def test_source_tag_is_applied(tmp_path: Path) -> None:
    selected = _run_filter([FIXTURE[2]], "review", tmp_path)
    assert selected[0]["source"] == "review"


class TestReplyDoesNotSelfTrigger:
    """GH-777: a reply quoting a severity token must not be a finding."""

    def test_re_reply_quoting_token_excluded(self, tmp_path: Path) -> None:
        row = {
            "id": 10,
            "user": {"login": "janusz", "type": "User"},
            "body": 'Re: Review Summary (review 123) — "CRITICAL: foo was removed" — refuted.',
        }
        assert _run_filter([row], "comment", tmp_path) == []

    def test_bot_re_reply_quoting_token_excluded(self, tmp_path: Path) -> None:
        # Even from a bot login, a Re: reply is a response, not a finding.
        row = {
            "id": 11,
            "user": {"login": "claude", "type": "Bot"},
            "body": "Re: BLOCKING finding — addressed in fixup abc123.",
        }
        assert _run_filter([row], "comment", tmp_path) == []

    def test_blockquoted_token_excluded(self, tmp_path: Path) -> None:
        row = {
            "id": 12,
            "user": {"login": "claude", "type": "Bot"},
            "body": "Responding below:\n> CRITICAL: null deref\n\nFixed, thanks.",
        }
        assert _run_filter([row], "comment", tmp_path) == []

    def test_inline_quoted_token_excluded(self, tmp_path: Path) -> None:
        row = {
            "id": 13,
            "user": {"login": "claude", "type": "Bot"},
            "body": 'The reviewer said "REQUIRED: rename" but that is done.',
        }
        assert _run_filter([row], "comment", tmp_path) == []

    def test_genuine_finding_with_quoted_variable_still_selected(self, tmp_path: Path) -> None:
        # Token is NOT inside quotes — a real finding is still flagged.
        row = {
            "id": 14,
            "user": {"login": "claude", "type": "Bot"},
            "body": 'CRITICAL: variable "foo" is undefined',
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [14]
