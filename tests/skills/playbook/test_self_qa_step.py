"""User-facing plays record a self-QA video before review (GH-1827).

The ``self-qa-evidence`` step runs right before the review request, so
the reviewer opens a narrated demo instead of a bare diff. It skips
with a printed line, keeps the external-publish gates of the skills it
delegates to, and a project can turn it off or record without
publishing. Reflection stays the last step of every play (GH-1822); that
is pinned in test_session_reflection_step.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.skills.playbook.play_expansion import VERIFY_AC, expand_plays

SELF_QA = "Record self-QA video and review pack"
REVIEW_REQUEST = "Request review"
SHIPPING_PLAYS = ["bugfix", "feature", "local-only", "structured-spec"]
USER_FACING_PLAYS = [*SHIPPING_PLAYS, "business"]
PLAYS_WITHOUT_SELF_QA = ["investigation", "pr-continuation"]


@pytest.fixture(scope="module")
def plays(playbook: dict[str, Any]) -> dict[str, list[str]]:
    return {
        name: [step["subject"] for step in steps] for name, steps in expand_plays(playbook).items()
    }


@pytest.fixture(scope="module")
def step(playbook: dict[str, Any]) -> dict[str, Any]:
    (only,) = playbook["fragments"]["self-qa-evidence"]
    return only


@pytest.fixture(scope="module")
def prompt(step: dict[str, Any]) -> str:
    return " ".join(step["prompt"].split())


@pytest.mark.parametrize("play", USER_FACING_PLAYS)
def test_user_facing_play_records_self_qa_once(plays: dict[str, list[str]], play: str) -> None:
    assert plays[play].count(SELF_QA) == 1


@pytest.mark.parametrize("play", SHIPPING_PLAYS)
def test_self_qa_directly_precedes_review_request(plays: dict[str, list[str]], play: str) -> None:
    subjects = plays[play]

    assert subjects[subjects.index(SELF_QA) + 1] == REVIEW_REQUEST


@pytest.mark.parametrize("play", USER_FACING_PLAYS)
def test_self_qa_runs_before_verify_ac(plays: dict[str, list[str]], play: str) -> None:
    subjects = plays[play]

    assert subjects.index(SELF_QA) < subjects.index(VERIFY_AC)


def test_local_only_records_self_qa_only_on_the_pr_path(playbook: dict[str, Any]) -> None:
    conditions = [
        step["condition"]
        for step in expand_plays(playbook)["local-only"]
        if step["subject"] == SELF_QA
    ]

    assert conditions == ["if-pr-decided"]


@pytest.mark.parametrize("play", PLAYS_WITHOUT_SELF_QA)
def test_plays_without_a_new_change_skip_self_qa(plays: dict[str, list[str]], play: str) -> None:
    assert SELF_QA not in plays[play]


def test_step_chains_scope_capture_and_pack(step: dict[str, Any]) -> None:
    assert step["skills"] == [
        "dev10x:qa-scope",
        "dev10x-qa:qa-self",
        "dev10x-qa:review-pack",
    ]


@pytest.mark.parametrize(
    "phrase",
    [
        "--exploratory",
        "narrated video",
        'print "Self-QA skipped: no user-facing change"',
        "no runnable environment",
        'print "Self-QA skipped: <reason>"',
        "dev10x-qa:qa-publish or dev10x-qa:yt-upload",
        "dev10x-qa:review-pack with --no-request-review",
    ],
)
def test_prompt_wires_the_pipeline_and_skip_notes(prompt: str, phrase: str) -> None:
    assert phrase in prompt


@pytest.mark.parametrize(
    "phrase",
    [
        "Keep every external-publish gate",
        "staging footage only, never production",
        "no public host for a private repository",
        "never requests review itself",
    ],
)
def test_prompt_keeps_external_publish_gates(prompt: str, phrase: str) -> None:
    assert phrase in prompt


def test_qa_off_mode_drops_the_step(step: dict[str, Any]) -> None:
    assert step["modes"]["qa-off"] == "skip"


def test_qa_record_only_mode_never_publishes(step: dict[str, Any]) -> None:
    record_only = step["modes"]["qa-record-only"]

    assert record_only["skills"] == ["dev10x:qa-scope", "dev10x-qa:qa-self"]
    assert "Publish nothing" in " ".join(record_only["prompt"].split())


class TestContinuationRefresh:
    """pr-continuation re-records only when the UI changed (GH-1848)."""

    REFRESH = "Re-record self-QA video if the UI changed"
    RE_REVIEW = "Request re-review"

    @pytest.fixture(scope="class")
    def refresh_step(self, playbook: dict[str, Any]) -> dict[str, Any]:
        (only,) = playbook["fragments"]["self-qa-evidence-refresh"]
        return only

    @pytest.fixture(scope="class")
    def refresh_prompt(self, refresh_step: dict[str, Any]) -> str:
        return " ".join(refresh_step["prompt"].split())

    def test_continuation_refreshes_once(self, plays: dict[str, list[str]]) -> None:
        assert plays["pr-continuation"].count(self.REFRESH) == 1

    def test_refresh_directly_precedes_re_review(self, plays: dict[str, list[str]]) -> None:
        subjects = plays["pr-continuation"]

        assert subjects[subjects.index(self.REFRESH) + 1] == self.RE_REVIEW

    def test_refresh_runs_after_grooming(self, plays: dict[str, list[str]]) -> None:
        subjects = plays["pr-continuation"]

        assert subjects.index("Groom commit history") < subjects.index(self.REFRESH)

    def test_refresh_runs_before_verify_ac(self, plays: dict[str, list[str]]) -> None:
        subjects = plays["pr-continuation"]

        assert subjects.index(self.REFRESH) < subjects.index(VERIFY_AC)

    @pytest.mark.parametrize("play", USER_FACING_PLAYS)
    def test_first_recording_plays_do_not_refresh(
        self, plays: dict[str, list[str]], play: str
    ) -> None:
        assert self.REFRESH not in plays[play]

    @pytest.mark.parametrize(
        "phrase",
        [
            "scripts/video-freshness.py",
            "configured ui_globs",
            'print "Self-QA refresh skipped: no earlier recording"',
            'print "Self-QA evidence still current: <verdict>"',
            "On exit 1 the video is stale",
            "--exploratory <PR>",
            "dev10x-qa:review-pack with --no-request-review",
            'print "Self-QA refresh skipped: <reason>"',
        ],
    )
    def test_prompt_reuses_the_freshness_check(self, refresh_prompt: str, phrase: str) -> None:
        assert phrase in refresh_prompt

    @pytest.mark.parametrize(
        "phrase",
        [
            "Keep every external-publish gate",
            "staging footage only, never production",
            "no public host for a private repository",
            "never requests review itself",
        ],
    )
    def test_prompt_keeps_external_publish_gates(self, refresh_prompt: str, phrase: str) -> None:
        assert phrase in refresh_prompt

    def test_qa_off_mode_drops_the_step(self, refresh_step: dict[str, Any]) -> None:
        assert refresh_step["modes"]["qa-off"] == "skip"

    def test_qa_record_only_mode_never_publishes(self, refresh_step: dict[str, Any]) -> None:
        record_only = " ".join(refresh_step["modes"]["qa-record-only"]["prompt"].split())

        assert "publish nothing" in record_only
