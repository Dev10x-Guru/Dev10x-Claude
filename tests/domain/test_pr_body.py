"""GH-945: PR-body hygiene rules mirroring the hygiene-bot findings."""

import pytest

from dev10x.domain.pr_body import (
    SO_CAN_MARKER,
    WANTS_MARKER,
    WHEN_MARKER,
    has_fixes_trailer,
    job_story_error,
    missing_job_story_markers,
    normalize_pr_body,
)

COMPLIANT_STORY = (
    "**When** an unattended run creates PRs, **the plugin maintainer "
    "wants to** get compliant bodies on the first try, **so the crew can** "
    "skip the fix-and-edit round."
)
FIXES_URL = "https://github.com/Dev10x-Guru/dev10x-claude/issues/945"


def test_compliant_job_story_has_no_missing_markers():
    assert missing_job_story_markers(job_story=COMPLIANT_STORY) == []


def test_compliant_job_story_yields_no_error():
    assert job_story_error(job_story=COMPLIANT_STORY) is None


def test_first_person_legacy_story_is_accepted():
    story = "**When** X, **I want to** Y, **so I can** Z."
    assert missing_job_story_markers(job_story=story) == []


@pytest.mark.parametrize(
    "job_story,expected",
    [
        (
            "**the maintainer wants to** Y, **so the crew can** Z.",
            [WHEN_MARKER],
        ),
        (
            "**When** X, the maintainer wants to Y, **so the crew can** Z.",
            [WANTS_MARKER],
        ),
        (
            "**When** X, **the maintainer wants to** Y, **so the crew doesn't burn a round.**",
            [SO_CAN_MARKER],
        ),
        (
            "When X, the maintainer wants to Y, so the crew can Z.",
            [WHEN_MARKER, WANTS_MARKER, SO_CAN_MARKER],
        ),
    ],
)
def test_missing_markers_are_reported(job_story, expected):
    assert missing_job_story_markers(job_story=job_story) == expected


def test_error_names_the_missing_marker_and_the_expected_format():
    error = job_story_error(job_story="**When** X, **I want to** Y, so I can Z.")
    assert SO_CAN_MARKER in error
    assert "references/git-jtbd.md" in error


def test_bare_separator_after_fixes_is_dropped():
    body = f"Story\n\n---\n\n- commit\n\nFixes: {FIXES_URL}\n\n---\n"
    assert normalize_pr_body(body=body) == f"Story\n\n---\n\n- commit\n\nFixes: {FIXES_URL}"


def test_substantive_trailer_is_relocated_above_fixes():
    body = f"Story\n\nFixes: {FIXES_URL}\n\n---\n\n## Checklist\n- [ ] tested\n"
    assert normalize_pr_body(body=body) == (
        f"Story\n\n---\n\n## Checklist\n- [ ] tested\n\nFixes: {FIXES_URL}"
    )


def test_already_compliant_body_is_unchanged_apart_from_trailing_whitespace():
    body = f"Story\n\n---\n\n- commit\n\nFixes: {FIXES_URL}"
    assert normalize_pr_body(body=f"{body}\n\n") == body


def test_body_without_fixes_trailer_is_left_alone():
    body = "Story\n\n---\n\n- commit"
    assert normalize_pr_body(body=f"{body}\n") == body


def test_only_the_last_fixes_line_anchors_normalization():
    body = f"Fixes: mentioned inline\n\nStory\n\nFixes: {FIXES_URL}\n\n---"
    assert normalize_pr_body(body=body) == (
        f"Fixes: mentioned inline\n\nStory\n\nFixes: {FIXES_URL}"
    )


def test_fixes_only_body_normalizes_to_the_single_line():
    assert normalize_pr_body(body=f"\n\nFixes: {FIXES_URL}\n---\n") == f"Fixes: {FIXES_URL}"


def test_contiguous_fixes_block_is_kept_together():
    # GH-1107 F2: a bundle PR needs one Fixes line per issue, and only
    # a Fixes trailer auto-closes on a develop merge — splitting the run
    # would strand the earlier entries mid-body and leave those issues
    # open with nothing explaining why.
    body = f"Story\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2\n\n---"

    assert normalize_pr_body(body=body) == (f"Story\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2")


def test_trailing_content_moves_above_a_multi_line_fixes_block():
    body = f"Story\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2\n\nstray note"

    assert normalize_pr_body(body=body) == (
        f"Story\n\nstray note\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2"
    )


def test_self_motivated_fixes_trailer_is_detected():
    assert has_fixes_trailer(body="Story\n\nFixes: none — self-motivated")


def test_missing_fixes_trailer_is_detected():
    assert not has_fixes_trailer(body="Story\n\n---")
