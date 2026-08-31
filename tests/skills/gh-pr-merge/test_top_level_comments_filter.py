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


def _run_filter(
    rows: list[dict],
    src: str,
    tmp_path: Path,
    cross_surface: list[dict] | None = None,
    pr_body: str = "",
) -> list[dict]:
    """Run the filter over one surface.

    ``cross_surface`` is the OTHER surface's raw rows, which the real caller
    always supplies so a ``Re:``-keyed reply disposes of its finding across
    surfaces (GH-1002). Defaults to empty, matching a single-surface scan.

    ``pr_body`` is the PR description, which the real caller also always
    supplies so a round that exists only as a body checklist refresh
    supersedes earlier rounds (GH-1085). Defaults to empty — a body that
    declares no round.
    """
    fixture = tmp_path / "rows.json"
    fixture.write_text(json.dumps(rows))
    result = subprocess.run(
        [
            "jq",
            "-f",
            str(FILTER),
            "--arg",
            "src",
            src,
            "--arg",
            "pr_body",
            pr_body,
            "--argjson",
            "extra",
            json.dumps(cross_surface or []),
            str(fixture),
        ],
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

    def test_keyed_reply_still_never_self_triggers(self, tmp_path: Path) -> None:
        # GH-777 must survive GH-907: a reply that keys a finding id AND
        # quotes a severity token is still a response, never a finding.
        rows = [
            {
                "id": 5082812952,
                "user": {"login": "claude", "type": "Bot"},
                "body": "**REQUIRED**: add a footer link",
            },
            {
                "id": 5083000015,
                "user": {"login": "claude", "type": "Bot"},
                "body": "Re: comment 5082812952 — REQUIRED footer link addressed.",
            },
        ]
        # Both drop out: the finding is answered, the reply never counts.
        assert _run_filter(rows, "comment", tmp_path) == []


class TestKeyedReplyDisposesFinding:
    """GH-907 / GH-884: Check 1b promises a finding is 'addressed' once a later
    comment replies to it, but nothing mapped a reply back to its finding — so
    `blocking_count` never returned to 0 and the merge gate dead-ended. A reply
    whose `Re:` line carries the finding's comment id now drops that finding."""

    FINDING = {
        "id": 5082812952,
        "user": {"login": "claude", "type": "Bot"},
        "body": "**REQUIRED**: Add a footer link at the end of the PR body",
    }
    OTHER = {
        "id": 5082900001,
        "user": {"login": "claude", "type": "Bot"},
        "body": "CRITICAL: missing timeout on the subprocess call",
    }

    def test_unanswered_finding_still_blocks(self, tmp_path: Path) -> None:
        selected = _run_filter([self.FINDING], "comment", tmp_path)
        assert [r["id"] for r in selected] == [5082812952]

    @pytest.mark.parametrize(
        "reply_body",
        [
            "Re: comment 5082812952 (**REQUIRED** footer link) — addressed.",
            "Re: #5082812952 — fixed in abc123.",
            "Re: 5082812952 — declined, see GH-999.",
        ],
    )
    def test_keyed_reply_drops_the_finding(self, reply_body: str, tmp_path: Path) -> None:
        reply = {"id": 5083000002, "user": {"login": "janusz", "type": "User"}, "body": reply_body}
        assert _run_filter([self.FINDING, reply], "comment", tmp_path) == []

    def test_only_the_keyed_finding_drops(self, tmp_path: Path) -> None:
        reply = {
            "id": 5083000002,
            "user": {"login": "janusz", "type": "User"},
            "body": "Re: comment 5082812952 — addressed.",
        }
        selected = _run_filter([self.FINDING, self.OTHER, reply], "comment", tmp_path)
        assert [r["id"] for r in selected] == [5082900001]

    def test_info_finding_disposed_by_keyed_reply(self, tmp_path: Path) -> None:
        # GH-808's needs_disposition bucket is cleared by the same key.
        rows = [
            {
                "id": 5083000003,
                "user": {"login": "claude", "type": "Bot"},
                "body": "INFO: consider adding render tests",
            },
            {
                "id": 5083000004,
                "user": {"login": "janusz", "type": "User"},
                "body": "Re: #5083000003 INFO — deferred to GH-999.",
            },
        ]
        assert _run_filter(rows, "comment", tmp_path) == []

    def test_unkeyed_re_reply_leaves_the_finding_blocking(self, tmp_path: Path) -> None:
        # A prose-only "Re:" with no id is not a disposition — the gate must
        # not be cleared by an unkeyed reply.
        reply = {
            "id": 5083000005,
            "user": {"login": "janusz", "type": "User"},
            "body": "Re: the footer link thing — addressed.",
        }
        selected = _run_filter([self.FINDING, reply], "comment", tmp_path)
        assert [r["id"] for r in selected] == [5082812952]

    def test_ticket_ref_in_reply_cannot_clear_a_finding(self, tmp_path: Path) -> None:
        # Short digit runs (GH-907, Round 4) stay under the 6-digit floor.
        rows = [
            {
                "id": 907,
                "user": {"login": "claude", "type": "Bot"},
                "body": "BLOCKING: null deref",
            },
            {
                "id": 5083000006,
                "user": {"login": "janusz", "type": "User"},
                "body": "Re: GH-907 Round 4 — unrelated note.",
            },
        ]
        selected = _run_filter(rows, "comment", tmp_path)
        assert [r["id"] for r in selected] == [907]

    def test_key_matched_outside_code_spans(self, tmp_path: Path) -> None:
        # The key is read from the RAW body, so backticking the id (the old
        # manual stale-finding workaround) is no longer load-bearing.
        reply = {
            "id": 5083000007,
            "user": {"login": "janusz", "type": "User"},
            "body": "Re: comment `5082812952` — addressed.",
        }
        assert _run_filter([self.FINDING, reply], "comment", tmp_path) == []

    def test_id_only_on_a_non_re_line_does_not_dispose(self, tmp_path: Path) -> None:
        # Only the "Re:" line carries keys; a bare id in prose is not a
        # disposition signal.
        row = {
            "id": 5083000008,
            "user": {"login": "claude", "type": "Bot"},
            "body": "REQUIRED: see also comment 5082812952 for context",
        }
        selected = _run_filter([self.FINDING, row], "comment", tmp_path)
        assert {r["id"] for r in selected} == {5082812952, 5083000008}

    def test_review_surface_uses_the_same_key(self, tmp_path: Path) -> None:
        rows = [
            {
                "id": 5082812952,
                "user": {"login": "rev-bot", "type": "Bot"},
                "body": "REQUIRED: real issue",
                "state": "CHANGES_REQUESTED",
            },
            {
                "id": 5083000009,
                "user": {"login": "janusz", "type": "User"},
                "body": "Re: comment 5082812952 — addressed.",
            },
        ]
        assert _run_filter(rows, "review", tmp_path) == []


class TestKeyedReplyIsFoundBelowAPreamble:
    """GH-1057: a keyed disposition with a preamble line was invisible.

    ``is_reply`` tested the WHOLE body against ``^[[:space:]]*Re:``, and jq
    anchors that at the start of the string — so the documented
    ``gh-pr-respond`` shape, which opens with a
    ``Merge-gate dispositions (keyed):`` line before its ``Re:`` lines,
    matched nothing. Two failures followed from the one cause: the
    disposition self-triggered as a NEW finding, and ``reply_target_ids``
    (gated on ``is_reply``) never collected its keys, so none of the
    findings it answered dropped out.

    Net effect in the field: every disposition posted to satisfy Check 1b
    raised ``needs_disposition_count`` by one — a feedback loop with no
    mechanical exit.
    """

    FINDINGS = [
        {
            "id": 5371568079,
            "user": {"login": "claude", "type": "Bot"},
            "body": "INFO: consider renaming the helper",
        },
        {
            "id": 5371852962,
            "user": {"login": "claude", "type": "Bot"},
            "body": "NOTE: the docstring drifted",
        },
    ]
    KEYED_DISPOSITION = {
        "id": 5372056101,
        "user": {"login": "claude", "type": "Bot"},
        "body": (
            "Merge-gate dispositions (keyed):\n"
            "\n"
            "Re: comment 5371568079 — addressed in abc1234.\n"
            "Re: comment 5371852962 — declined with evidence: INFO is out of scope.\n"
        ),
    }

    def test_findings_block_before_the_disposition_is_posted(self, tmp_path: Path) -> None:
        """The premise — kept as a live assertion so a fix that clears these
        unconditionally is caught."""
        selected = _run_filter(self.FINDINGS, "comment", tmp_path)
        assert {row["id"] for row in selected} == {5371568079, 5371852962}

    def test_preamble_keyed_disposition_clears_every_keyed_finding(self, tmp_path: Path) -> None:
        rows = [*self.FINDINGS, self.KEYED_DISPOSITION]
        assert _run_filter(rows, "comment", tmp_path) == []

    def test_the_disposition_itself_is_not_a_finding(self, tmp_path: Path) -> None:
        """It carries the word INFO in its declined-with-evidence line, which
        is exactly how it became a fourth finding."""
        assert _run_filter([self.KEYED_DISPOSITION], "comment", tmp_path) == []

    def test_keys_are_collected_across_surfaces(self, tmp_path: Path) -> None:
        """gh-pr-respond posts review-body replies as issue comments, so the
        preamble shape has to work through the cross-surface union too."""
        selected = _run_filter(
            self.FINDINGS,
            "review",
            tmp_path,
            cross_surface=[self.KEYED_DISPOSITION],
        )
        assert selected == []

    @pytest.mark.parametrize(
        "body",
        [
            "Dispositions:\n\nRe: comment 5371568079 — done.",
            "Round 3 follow-up\n\n  Re: #5371568079 — fixed.",
            "Header\n\nRe: 5371568079 — declined.",
        ],
    )
    def test_key_position_within_the_body_does_not_matter(self, body: str, tmp_path: Path) -> None:
        reply = {"id": 5372056102, "user": {"login": "janusz", "type": "User"}, "body": body}
        assert _run_filter([self.FINDINGS[0], reply], "comment", tmp_path) == []

    def test_a_bare_id_on_a_non_re_line_still_does_not_dispose(self, tmp_path: Path) -> None:
        """Widening WHERE a ``Re:`` line may sit must not widen WHAT counts as
        a key — only ``Re:`` lines carry them."""
        row = {
            "id": 5372056103,
            "user": {"login": "claude", "type": "Bot"},
            "body": "Preamble\n\nREQUIRED: see comment 5371568079 for context",
        }
        selected = _run_filter([self.FINDINGS[0], row], "comment", tmp_path)
        assert {r["id"] for r in selected} == {5371568079, 5372056103}


class TestInfoFamilyExoneration:
    """GH-1057: an INFO token on a line that says it is already handled.

    ``exonerated_line`` recognised exoneration cues only around
    REQUIRED/CRITICAL/BLOCKING, so a reviewer's own "all INFO items
    addressed" wrap-up kept registering as a live INFO finding. The cue
    shapes are unchanged — only the token set widens — and the direction is
    safe: an INFO finding does not hard-block, it only needs a disposition.
    """

    @pytest.mark.parametrize(
        "body",
        [
            "No INFO items remain.",
            "All INFO items addressed in the latest round.",
            "Every SUGGESTION resolved.",
            "NOTE: none",
            "✅ INFO items verified",
        ],
    )
    def test_exonerated_info_line_is_not_a_finding(self, body: str, tmp_path: Path) -> None:
        row = {"id": 5372056104, "user": {"login": "claude", "type": "Bot"}, "body": body}
        assert _run_filter([row], "comment", tmp_path) == []

    @pytest.mark.parametrize(
        "body",
        [
            "INFO: the retry helper duplicates logic in client.py",
            "SUGGESTION: extract the parser",
            "NOTE: this was previously addressed elsewhere, but regressed",
        ],
    )
    def test_live_info_findings_still_need_disposition(self, body: str, tmp_path: Path) -> None:
        """The cue must be on the same line and must actually exonerate —
        prose merely mentioning a resolution verb keeps blocking, which is
        the intended bias."""
        row = {"id": 5372056105, "user": {"login": "claude", "type": "Bot"}, "body": body}
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [5372056105]

    def test_blocking_exoneration_is_unchanged(self, tmp_path: Path) -> None:
        rows = [
            {
                "id": 5372056106,
                "user": {"login": "claude", "type": "Bot"},
                "body": "CRITICAL: this was previously fine",
            },
            {
                "id": 5372056107,
                "user": {"login": "claude", "type": "Bot"},
                "body": "No CRITICAL issues found.",
            },
        ]
        selected = _run_filter(rows, "comment", tmp_path)
        assert [r["id"] for r in selected] == [5372056106]


class TestInfoSeverityDisposition:
    """GH-808 F1: non-blocking INFO/NOTE/SUGGESTION bot findings surface with
    severity=info so they require a disposition; blocking findings keep
    severity=blocking; untokened bot prose stays excluded."""

    def test_info_marker_selected_with_info_severity(self, tmp_path: Path) -> None:
        row = {
            "id": 20,
            "user": {"login": "claude", "type": "Bot"},
            "body": "INFO: consider adding component render tests",
        }
        selected = _run_filter([row], "review", tmp_path)
        assert [r["id"] for r in selected] == [20]
        assert selected[0]["severity"] == "info"

    def test_suggestion_and_note_tokens_selected(self, tmp_path: Path) -> None:
        rows = [
            {"id": 21, "user": {"login": "claude", "type": "Bot"}, "body": "NOTE: minor nit"},
            {
                "id": 22,
                "user": {"login": "coderabbit", "type": "Bot"},
                "body": "SUGGESTION: rename var",
            },
        ]
        selected = _run_filter(rows, "review", tmp_path)
        assert {r["id"] for r in selected} == {21, 22}
        assert all(r["severity"] == "info" for r in selected)

    def test_blocking_finding_keeps_blocking_severity(self, tmp_path: Path) -> None:
        # FIXTURE[2] is id 3, a BLOCKING bot finding.
        selected = _run_filter([FIXTURE[2]], "comment", tmp_path)
        assert selected[0]["severity"] == "blocking"

    def test_plain_bot_prose_without_token_excluded(self, tmp_path: Path) -> None:
        # A routine bot LGTM with no severity token must NOT flood the gate.
        row = {"id": 23, "user": {"login": "claude", "type": "Bot"}, "body": "LGTM, ship it"}
        assert _run_filter([row], "review", tmp_path) == []

    def test_re_reply_to_info_not_self_triggered(self, tmp_path: Path) -> None:
        row = {
            "id": 24,
            "user": {"login": "claude", "type": "Bot"},
            "body": "Re: INFO: add tests — deferred to GH-999.",
        }
        assert _run_filter([row], "comment", tmp_path) == []


class TestRoundSummaryWrapperExcluded:
    """GH-858 F2: the reviewer's own '## Review Summary (Round N)' comment
    restates fixed findings under 'Addressed since last review'; only its
    'Remaining issues' section should be scanned for live blockers."""

    def test_round_summary_with_no_remaining_issues_not_flagged(self, tmp_path: Path) -> None:
        row = {
            "id": 30,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                "## Review Summary (Round 3)\n\n"
                "### Addressed since last review\n- REQUIRED: fixed null check\n\n"
                "### Remaining issues\n- none"
            ),
        }
        assert _run_filter([row], "comment", tmp_path) == []

    def test_round_summary_with_genuine_remaining_issue_still_flagged(
        self, tmp_path: Path
    ) -> None:
        row = {
            "id": 31,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                "## Review Summary (Round 3)\n\n"
                "### Addressed since last review\n- REQUIRED: fixed null check\n\n"
                "### Remaining issues\n- CRITICAL: still missing timeout"
            ),
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [31]

    def test_round_summary_missing_remaining_section_treated_as_clean(
        self, tmp_path: Path
    ) -> None:
        row = {
            "id": 32,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                "## Review Summary (Round 1)\n\n### Addressed since last review\n- BLOCKING: x"
            ),
        }
        assert _run_filter([row], "comment", tmp_path) == []

    def test_normal_bot_finding_still_scans_full_body(self, tmp_path: Path) -> None:
        # A non-summary bot comment must keep full-body scanning (no regression).
        row = {
            "id": 33,
            "user": {"login": "claude", "type": "Bot"},
            "body": "REQUIRED: fix the missing null guard in handler",
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [33]


class TestOnlyLatestRoundIsAuthoritative:
    """GH-873 F3: with several '## Review Summary (Round N)' comments, only the
    highest round is authoritative — earlier rounds' 'Remaining issues' are a
    historical snapshot and must not false-block once a later round supersedes
    them."""

    @staticmethod
    def _round(cid: int, n: int, remaining: str) -> dict:
        return {
            "id": cid,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                f"## Review Summary (Round {n})\n\n"
                "### Addressed since last review\n- REQUIRED: earlier fix\n\n"
                f"### Remaining issues\n- {remaining}"
            ),
        }

    def test_green_final_round_clears_stale_earlier_rounds(self, tmp_path: Path) -> None:
        rows = [
            self._round(40, 1, "CRITICAL: missing timeout"),
            self._round(41, 3, "REQUIRED: null guard"),
            self._round(42, 4, "none"),
        ]
        # Round 4 (latest) is clean; Rounds 1 and 3 are superseded.
        assert _run_filter(rows, "comment", tmp_path) == []

    def test_latest_round_with_live_issue_still_flagged(self, tmp_path: Path) -> None:
        rows = [
            self._round(43, 1, "CRITICAL: missing timeout"),
            self._round(44, 3, "REQUIRED: still missing null guard"),
        ]
        # Only Round 3 (latest) is authoritative and it has a live issue.
        selected = _run_filter(rows, "comment", tmp_path)
        assert [r["id"] for r in selected] == [44]

    def test_single_round_summary_unchanged(self, tmp_path: Path) -> None:
        # One round == the latest round; the GH-858 F2 behaviour is preserved.
        rows = [self._round(45, 2, "CRITICAL: still broken")]
        selected = _run_filter(rows, "comment", tmp_path)
        assert [r["id"] for r in selected] == [45]

    def test_superseded_round_excluded_but_non_summary_finding_kept(self, tmp_path: Path) -> None:
        rows = [
            self._round(46, 1, "CRITICAL: old issue"),
            self._round(47, 2, "none"),
            {
                "id": 48,
                "user": {"login": "claude", "type": "Bot"},
                "body": "REQUIRED: fix the missing null guard in handler",
            },
        ]
        # Round 1 superseded, Round 2 clean, standalone finding still flagged.
        selected = _run_filter(rows, "comment", tmp_path)
        assert [r["id"] for r in selected] == [48]


class TestBodyOnlyRoundRefresh:
    """GH-1085: a round whose only refresh is a PR-body checklist supersedes
    the previous round's 'Remaining issues'.

    Observed on Brave-Labs/zebra#2289: a Round 3 that posted no
    '## Review Summary (Round 3)' comment left Round 2's INFO blocking
    Check 1b, with no sanctioned exit."""

    @staticmethod
    def _round(cid: int, n: int, remaining: str) -> dict:
        return {
            "id": cid,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                f"## Review Summary (Round {n})\n\n"
                "### Addressed since last review\n- REQUIRED: earlier fix\n\n"
                f"### Remaining issues\n- {remaining}"
            ),
        }

    def test_body_round_supersedes_the_previous_round_summary(self, tmp_path: Path) -> None:
        rows = [self._round(60, 2, "INFO: consider extracting a helper")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="## Review checklist\n\n- [x] Round 3 review complete\n",
        )
        assert selected == []

    def test_body_round_does_not_clear_the_latest_round(self, tmp_path: Path) -> None:
        """A live remaining issue from the LATEST round still blocks."""
        rows = [self._round(61, 3, "REQUIRED: still missing the null guard")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="## Review checklist\n\n- [x] Round 3 review complete\n",
        )
        assert [r["id"] for r in selected] == [61]

    def test_body_without_a_round_marker_changes_nothing(self, tmp_path: Path) -> None:
        rows = [self._round(62, 2, "REQUIRED: still missing the null guard")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="**When** X, **the maintainer wants to** Y, **so the team can** Z.",
        )
        assert [r["id"] for r in selected] == [62]

    def test_review_mention_without_a_round_is_not_a_marker(self, tmp_path: Path) -> None:
        """The round capture must yield nothing, not raise, on such a line."""
        rows = [self._round(68, 2, "REQUIRED: still missing the null guard")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="Review complete, no blockers remain.",
        )
        assert [r["id"] for r in selected] == [68]

    def test_round_mention_without_review_is_not_a_marker(self, tmp_path: Path) -> None:
        """The marker demands both cues — a bare 'round' is not a round."""
        rows = [self._round(63, 2, "REQUIRED: still missing the null guard")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="Third round of load testing is scheduled for Friday.",
        )
        assert [r["id"] for r in selected] == [63]

    def test_body_round_below_the_latest_comment_round_is_ignored(self, tmp_path: Path) -> None:
        rows = [self._round(64, 4, "REQUIRED: still missing the null guard")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="- [x] Round 2 review complete\n",
        )
        assert [r["id"] for r in selected] == [64]

    def test_highest_body_round_wins_across_lines(self, tmp_path: Path) -> None:
        rows = [self._round(65, 2, "INFO: consider extracting a helper")]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="- [x] Review round 1 done\n- [x] Review round 3 done\n",
        )
        assert selected == []

    def test_standalone_finding_survives_a_body_round(self, tmp_path: Path) -> None:
        """Supersession touches round summaries only, never plain findings."""
        rows = [
            self._round(66, 2, "INFO: nit"),
            {
                "id": 67,
                "user": {"login": "claude", "type": "Bot"},
                "body": "REQUIRED: fix the missing null guard in handler",
            },
        ]
        selected = _run_filter(
            rows,
            "comment",
            tmp_path,
            pr_body="- [x] Round 3 review complete\n",
        )
        assert [r["id"] for r in selected] == [67]


class TestCrossSurfaceDisposition:
    """GH-1002: a keyed reply must dispose of its finding on EITHER surface.

    The caller scans issue comments and review bodies in two jq invocations.
    Scanning replies only within the current array made the disposition
    surface-local, so a blocking review-BODY finding could never be cleared —
    `gh-pr-respond` posts body-finding replies as issue comments (GH-907,
    GH-920), which land in the other array. The only exits were rewriting the
    reviewer's own body or bypassing the merge gate.
    """

    REVIEW_FINDING = {
        "id": 4839278701,
        "user": {"login": "claude", "type": "Bot"},
        "state": "COMMENTED",
        "body": "## Claude Code Review (Round 1)\n\n**CRITICAL** — Step 0 has no backing tool",
    }
    ISSUE_COMMENT_REPLY = {
        "id": 5159664533,
        "user": {"login": "janusz-10x", "type": "Bot"},
        "body": "Re: comment 4839278701 — Claude Code Review (Round 1)\n\nBoth findings fixed.",
    }

    def test_review_body_finding_blocks_without_a_reply(self, tmp_path: Path) -> None:
        selected = _run_filter([self.REVIEW_FINDING], "review", tmp_path)
        assert [row["id"] for row in selected] == [4839278701]

    def test_issue_comment_reply_disposes_of_a_review_body_finding(self, tmp_path: Path) -> None:
        """The regression: reply on `comments`, finding on `reviews`."""
        selected = _run_filter(
            [self.REVIEW_FINDING],
            "review",
            tmp_path,
            cross_surface=[self.ISSUE_COMMENT_REPLY],
        )
        assert selected == []

    def test_cross_surface_union_does_not_clear_an_unrelated_finding(self, tmp_path: Path) -> None:
        """Widening the scan must not turn into a blanket clear."""
        unrelated = {
            "id": 4839299999,
            "user": {"login": "claude", "type": "Bot"},
            "state": "COMMENTED",
            "body": "**CRITICAL** — a different, still-unanswered finding",
        }
        selected = _run_filter(
            [self.REVIEW_FINDING, unrelated],
            "review",
            tmp_path,
            cross_surface=[self.ISSUE_COMMENT_REPLY],
        )
        assert [row["id"] for row in selected] == [4839299999]

    def test_reply_on_reviews_disposes_of_an_issue_comment_finding(self, tmp_path: Path) -> None:
        """The union is symmetric — it works in both directions."""
        issue_finding = {
            "id": 5159183532,
            "user": {"login": "claude", "type": "Bot"},
            "body": "- **REQUIRED:** Fixup commits remaining.",
        }
        review_reply = {
            "id": 4839400000,
            "user": {"login": "janusz-10x", "type": "Bot"},
            "state": "COMMENTED",
            "body": "Re: comment 5159183532 — squashed.",
        }
        selected = _run_filter([issue_finding], "comment", tmp_path, cross_surface=[review_reply])
        assert selected == []


class TestRemainingIssuesSectionIsBounded:
    """GH-1011 field case 1: the section scan ran past its own section.

    `scan_body` captured `(?s).*` to end-of-body, so a summary that declared
    `### Remaining issues` → `None` still blocked the merge on a severity
    token appearing in an unrelated LATER section — a false-positive-drops
    list restating the finding it had just dismissed. Observed on PR #2212,
    where the round summary said "Remaining issues: None" and the gate
    nonetheless reported a live *CRITICAL*.
    """

    @staticmethod
    def _summary(cid: int, remaining: str, trailer: str) -> dict:
        return {
            "id": cid,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                f"## Review Summary (Round 2)\n\n### Remaining issues\n{remaining}\n{trailer}"
            ),
        }

    def test_token_after_a_horizontal_rule_does_not_block(self, tmp_path: Path) -> None:
        row = self._summary(
            60,
            "None",
            "\n---\n\n### False positives dropped\n- *CRITICAL* was a misread of the retry loop\n",
        )
        assert _run_filter([row], "comment", tmp_path) == []

    def test_token_under_a_later_h3_heading_does_not_block(self, tmp_path: Path) -> None:
        row = self._summary(
            61,
            "None",
            "\n### Notes for the author\n- the earlier REQUIRED finding was withdrawn\n",
        )
        assert _run_filter([row], "comment", tmp_path) == []

    def test_token_under_a_later_h2_heading_does_not_block(self, tmp_path: Path) -> None:
        row = self._summary(
            62,
            "None",
            "\n## Appendix\n- BLOCKING appeared only in this quoted changelog\n",
        )
        assert _run_filter([row], "comment", tmp_path) == []

    def test_live_finding_inside_the_section_still_blocks(self, tmp_path: Path) -> None:
        """Bounding the scan must not stop it from seeing real findings."""
        row = self._summary(
            63,
            "- CRITICAL: the timeout is still unbounded",
            "\n---\n\n### False positives dropped\n- none this round\n",
        )
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [63]

    def test_multi_line_section_is_scanned_to_its_boundary(self, tmp_path: Path) -> None:
        """A finding on a later line of the section is inside the bound."""
        row = self._summary(
            64,
            "- first, harmless observation\n- second line\n- REQUIRED: add the guard",
            "\n---\n\n### Stats\n- 3 files reviewed\n",
        )
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [64]

    def test_section_running_to_end_of_body_still_scanned(self, tmp_path: Path) -> None:
        """No trailing boundary at all — the `$` alternative must match."""
        row = self._summary(65, "- REQUIRED: add the guard", "")
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [65]


class TestUnnumberedRoundSummary:
    """GH-1011 field case 2: a bare `## Review Summary` was not a summary.

    `is_round_summary` required a literal `(Round`, so an unnumbered first
    summary fell through to the full-body scan and re-triggered the stale
    severity tokens its own "Addressed since last review" section restates —
    even after a later round had cleared them. Observed on PR #2219.
    """

    BARE = {
        "id": 70,
        "user": {"login": "claude", "type": "Bot"},
        "body": (
            "## Review Summary\n\n"
            "### Addressed since last review\n- WARNING: fixed the stale import\n\n"
            "### Remaining issues\nNone\n"
        ),
    }

    def test_bare_summary_scans_only_its_remaining_issues(self, tmp_path: Path) -> None:
        assert _run_filter([self.BARE], "comment", tmp_path) == []

    def test_bare_summary_with_a_live_issue_still_blocks(self, tmp_path: Path) -> None:
        row = {
            "id": 71,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                "## Review Summary\n\n"
                "### Addressed since last review\n- REQUIRED: fixed the stale import\n\n"
                "### Remaining issues\n- REQUIRED: the retry loop is still unbounded\n"
            ),
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [71]

    def test_bare_summary_counts_as_round_one_and_is_superseded(self, tmp_path: Path) -> None:
        """The AC: unnumbered == round 1, so `(Round 2)` supersedes it."""
        round_two = {
            "id": 72,
            "user": {"login": "claude", "type": "Bot"},
            "body": "## Review Summary (Round 2)\n\n### Remaining issues\nNone\n",
        }
        stale = {
            "id": 73,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                "## Review Summary\n\n### Remaining issues\n- CRITICAL: unbounded retry loop\n"
            ),
        }
        assert _run_filter([stale, round_two], "comment", tmp_path) == []

    def test_bare_summary_alone_remains_authoritative(self, tmp_path: Path) -> None:
        """Round 1 >= latest round 1 — nothing supersedes a lone summary."""
        row = {
            "id": 74,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                "## Review Summary\n\n### Remaining issues\n- CRITICAL: unbounded retry loop\n"
            ),
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [74]

    def test_h3_review_summary_is_not_treated_as_the_wrapper(self, tmp_path: Path) -> None:
        """Broadening the heading match must not swallow a deeper heading."""
        row = {
            "id": 75,
            "user": {"login": "claude", "type": "Bot"},
            "body": "### Review Summary\n\nREQUIRED: fix the missing null guard\n",
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [75]


class TestMarkupFreeRoundSummary:
    """GH-1054 F2 (1): a numbered summary without heading markup.

    `is_round_summary` required a literal `##`, so a bot opening with a bare
    `Review Summary (Round 3)` line was not recognised as the wrapper — the
    supersedes logic never engaged and an earlier round kept blocking.
    """

    @staticmethod
    def _summary(cid: int, headline: str, remaining: str) -> dict:
        return {
            "id": cid,
            "user": {"login": "claude", "type": "Bot"},
            "body": (
                f"{headline}\n\n"
                "Addressed since last review\n- CRITICAL: fixed the null check\n\n"
                f"Remaining issues:\n{remaining}\n"
            ),
        }

    @pytest.mark.parametrize(
        "headline",
        [
            "Review Summary (Round 3)",
            "**Review Summary (Round 3)**",
            "_Review Summary (Round 3)_",
        ],
    )
    def test_markup_free_summary_scans_only_remaining_issues(
        self, headline: str, tmp_path: Path
    ) -> None:
        row = self._summary(80, headline, "None")
        assert _run_filter([row], "comment", tmp_path) == []

    def test_markup_free_summary_with_a_live_issue_still_blocks(self, tmp_path: Path) -> None:
        row = self._summary(81, "Review Summary (Round 3)", "- CRITICAL: retry loop unbounded")
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [81]

    def test_markup_free_round_number_is_read_not_defaulted(self, tmp_path: Path) -> None:
        """Round 3 must supersede Round 2 — not collapse to the round-1 default."""
        stale = {
            "id": 82,
            "user": {"login": "claude", "type": "Bot"},
            "body": "## Review Summary (Round 2)\n\n### Remaining issues\n- CRITICAL: old issue\n",
        }
        latest = self._summary(83, "Review Summary (Round 3)", "None")
        assert _run_filter([stale, latest], "comment", tmp_path) == []

    def test_unnumbered_markup_free_line_is_not_a_wrapper(self, tmp_path: Path) -> None:
        """Without `(Round N)` and without markup, it is prose — scan the body."""
        row = {
            "id": 84,
            "user": {"login": "claude", "type": "Bot"},
            "body": "Review Summary\n\nREQUIRED: fix the missing null guard\n",
        }
        selected = _run_filter([row], "comment", tmp_path)
        assert [r["id"] for r in selected] == [84]


class TestNegatedAndConfirmedSeverityTokens:
    """GH-1054 F2 (2): a severity token stating the OPPOSITE of a finding.

    "No CRITICAL issues found" / "All CRITICAL items fully addressed" /
    "✅ Fix verified — CRITICAL resolved" are the bot signing off, not
    blocking. The exemption set stays narrow on purpose: a false negative
    merges a real blocker, which is worse than a false positive the author
    can still answer with a keyed `Re:` reply.
    """

    @staticmethod
    def _row(cid: int, body: str) -> dict:
        return {"id": cid, "user": {"login": "claude", "type": "Bot"}, "body": body}

    @pytest.mark.parametrize(
        "body",
        [
            "No CRITICAL issues found in this round",
            "None of the REQUIRED items remain",
            "Zero BLOCKING findings",
            "CRITICAL: none",
            "**CRITICAL**: None",
            "BLOCKING: not found",
            "All CRITICAL items fully addressed",
            "Every REQUIRED change has been resolved",
            "All **BLOCKING** findings fixed",
            "✅ Fix verified — CRITICAL resolved",
            "✔ CRITICAL addressed in fixup abc123",
        ],
    )
    def test_exonerating_line_is_not_a_blocking_finding(self, body: str, tmp_path: Path) -> None:
        assert _run_filter([self._row(90, body)], "comment", tmp_path) == []

    @pytest.mark.parametrize(
        "body",
        [
            "CRITICAL: there is no timeout on the subprocess call",
            "REQUIRED: fix all the missing null guards",
            "BLOCKING: none of the handlers validate input, so add a guard",
            "✅ Tests pass\nCRITICAL: the retry loop is still unbounded",
            "CRITICAL: this was previously fine",
        ],
    )
    def test_genuine_finding_is_not_exonerated(self, body: str, tmp_path: Path) -> None:
        selected = _run_filter([self._row(91, body)], "comment", tmp_path)
        assert [r["id"] for r in selected] == [91]

    def test_exoneration_is_line_scoped(self, tmp_path: Path) -> None:
        """A sign-off line must not clear a live finding on another line."""
        body = "No CRITICAL issues found\n\nREQUIRED: add the missing timeout"
        selected = _run_filter([self._row(92, body)], "comment", tmp_path)
        assert [r["id"] for r in selected] == [92]
