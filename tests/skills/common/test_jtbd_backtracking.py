"""GH-1293: a crafted PR body must not stall release-notes collection.

`extract_jtbd_structured` runs over the body of every merged PR when
release notes are collected (`dev10x.skills.release.collect_prs`), and on
a repo that takes outside contributions those bodies are written by
strangers. A body offering many failing `**When**` start positions used
to cost ~8x per doubling — 6.8s at 18KB, minutes at GitHub's 65536-char
ceiling.

The budget here is deliberately loose. It is not a benchmark: it exists
to fail loudly on a return to super-linear behaviour, not to police
milliseconds on a shared runner.
"""

from __future__ import annotations

import time

import pytest

from dev10x.skills.common.jtbd import extract_jtbd_structured

# GitHub's own PR-body ceiling, so the guard covers the worst a body can be.
_MAX_BODY = 65536

# ~1000x the post-fix cost, and far under the pre-fix cost at this size.
_BUDGET_SECONDS = 2.0


def many_failing_anchors(size: int) -> str:
    """Every `**When**` opens a match that cannot complete."""
    unit = "**When** x, **the dealer wants** y, "
    return (unit * (size // len(unit) + 1))[:size]


def interleaved_noise(size: int) -> str:
    """Anchors separated by the `**` and `,` the patterns partition on."""
    unit = "**When** a, **bold**, b, **bold**, c, "
    return (unit * (size // len(unit) + 1))[:size]


@pytest.mark.parametrize(
    "craft", [many_failing_anchors, interleaved_noise], ids=["anchors", "noise"]
)
def test_a_hostile_body_does_not_stall_the_extractor(craft):
    body = craft(_MAX_BODY)

    started = time.perf_counter()
    extract_jtbd_structured(body=body)
    elapsed = time.perf_counter() - started

    assert elapsed < _BUDGET_SECONDS, (
        f"extraction took {elapsed:.1f}s on a {len(body)}-char body — "
        "the super-linear backtracking GH-1293 fixed is back"
    )


STORY = (
    "**When** reconciling a payout, **the dealer wants to** see each line"
    " item, **so the service writer can** resolve disputes."
)


class TestWindowingCostsNoStory:
    """The speed must not be bought with a story that stops extracting.

    Trading a loud failure for a quiet one is the defect GH-1291 closed;
    these pin that the window did not reintroduce it.
    """

    def test_a_story_buried_deep_in_a_huge_body_is_still_found(self):
        # The window starts at the story's own marker, not at the body's
        # first character, so position does not decide extractability.
        body = ("filler paragraph.\n\n" * 3000) + STORY

        assert extract_jtbd_structured(body=body) is not None

    def test_a_false_opening_marker_does_not_hide_the_real_story(self):
        # The first `**When**` need not be the story — a quoted example or
        # a malformed attempt can come first. Parking on it would drop the
        # real story below, so successive windows are scanned.
        body = many_failing_anchors(8000) + "\n\n" + STORY

        assert extract_jtbd_structured(body=body) is not None

    def test_finding_a_story_behind_false_markers_is_still_fast(self):
        body = many_failing_anchors(8000) + "\n\n" + STORY

        started = time.perf_counter()
        extract_jtbd_structured(body=body)
        elapsed = time.perf_counter() - started

        assert elapsed < _BUDGET_SECONDS

    def test_a_story_beyond_the_scanned_span_is_the_documented_limit(self):
        # Bounding the scan is the fix; this records where the bound
        # falls rather than leaving it to be discovered. Reaching here
        # takes a body that buries its story under 64KB of decoy
        # markers — not a shape a conformant PR body has.
        body = many_failing_anchors(_MAX_BODY) + "\n\n" + STORY

        assert extract_jtbd_structured(body=body) is None

    def test_a_story_padded_past_the_window_is_the_documented_limit(self):
        # A single clause longer than 4000 characters is not a Job Story
        # any more; recorded so the boundary is a decision, not a surprise.
        overlong = STORY.replace("see each line item", "see " + ("x" * 5000))

        assert extract_jtbd_structured(body=overlong) is None


def test_the_hostile_body_really_is_unmatched():
    """Pins that the shapes above exercise the failing path.

    If a crafted body ever started matching, the timing assertions would
    pass for the wrong reason — the engine would stop at the first hit
    instead of exhausting the search.
    """
    assert extract_jtbd_structured(body=many_failing_anchors(4096)) is None
    assert extract_jtbd_structured(body=interleaved_noise(4096)) is None
