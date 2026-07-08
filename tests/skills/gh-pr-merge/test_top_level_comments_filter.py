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


# GH-777: replies that address a finding must not re-trigger the scanner.
# The documented reply format begins "Re:" and quotes the finding title;
# quoted context (blockquotes, inline code) is stripped before the
# severity scan so a faithful quote is never itself a new blocker.


def test_re_reply_quoting_finding_not_flagged(tmp_path: Path) -> None:
    reply = {
        "id": 10,
        "user": {"login": "janusz-10x", "type": "Bot"},
        "body": (
            'Re: Review Summary (review 4643768329) — "CRITICAL: ddd override '
            'was REMOVED" — refuted; the diff only ADDS the entry.'
        ),
    }
    assert _run_filter([reply], "comment", tmp_path) == []


def test_blockquoted_token_not_flagged(tmp_path: Path) -> None:
    quoting = {
        "id": 11,
        "user": {"login": "claude", "type": "Bot"},
        "body": "Addressed the finding:\n> CRITICAL: null deref in handler\nFixed in abc123.",
    }
    assert _run_filter([quoting], "comment", tmp_path) == []


def test_inline_code_quoted_token_not_flagged(tmp_path: Path) -> None:
    quoting = {
        "id": 12,
        "user": {"login": "claude", "type": "Bot"},
        "body": "The `CRITICAL` label from the prior review was addressed.",
    }
    assert _run_filter([quoting], "comment", tmp_path) == []


def test_paraphrased_lowercase_token_not_flagged(tmp_path: Path) -> None:
    paraphrase = {
        "id": 13,
        "user": {"login": "claude", "type": "Bot"},
        "body": "addressed the critical ddd override note (paraphrased, no token).",
    }
    assert _run_filter([paraphrase], "comment", tmp_path) == []


def test_finding_plus_re_reply_only_finding_counts(tmp_path: Path) -> None:
    finding = {
        "id": 20,
        "user": {"login": "claude", "type": "Bot"},
        "body": "CRITICAL: null deref",
    }
    reply = {
        "id": 21,
        "user": {"login": "janusz-10x", "type": "Bot"},
        "body": 'Re: "CRITICAL: null deref" — fixed in abc123.',
    }
    selected = _run_filter([finding, reply], "comment", tmp_path)
    assert [row["id"] for row in selected] == [20]
