"""Regression tests for the verify-acc-dod default checks (GH-736).

A skill-audit caught the work-on completion gate offering "Work complete
(Recommended)" while the "No unresolved review threads" check was failing
after the supervisor had explicitly *deferred* review threads. The honest
fix is for the ``review-deferred`` mode to skip the unresolved-threads
check (so the DoD reflects the agreed scope) — not to paper over a red
check with gate framing.

These tests pin the ``modes`` mapping on the relevant checks so the
``review-deferred`` contract cannot silently regress.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

DEFAULTS = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "verify-acc-dod"
    / "references"
    / "defaults.yaml"
)

# Work types whose DoD includes a review-thread / review-request workflow.
REVIEW_WORK_TYPES = ("feature", "bugfix", "pr-continuation")


@pytest.fixture(scope="module")
def defaults() -> dict:
    return yaml.safe_load(DEFAULTS.read_text())["defaults"]


def _check_by_name(checks: list[dict], name: str) -> dict:
    matches = [check for check in checks if check["name"] == name]
    assert len(matches) == 1, f"expected exactly one {name!r} check, found {len(matches)}"
    return matches[0]


@pytest.mark.parametrize("work_type", REVIEW_WORK_TYPES)
def test_review_deferred_skips_unresolved_threads(defaults: dict, work_type: str) -> None:
    check = _check_by_name(defaults[work_type]["checks"], "No unresolved review threads")
    assert check["modes"]["review-deferred"]["skip"] is True


@pytest.mark.parametrize(
    "work_type,request_check",
    [
        ("feature", "Review requested"),
        ("bugfix", "Review requested"),
        ("pr-continuation", "Re-review requested"),
    ],
)
def test_review_deferred_skips_review_request(
    defaults: dict, work_type: str, request_check: str
) -> None:
    check = _check_by_name(defaults[work_type]["checks"], request_check)
    assert check["modes"]["review-deferred"]["skip"] is True


@pytest.mark.parametrize("work_type", REVIEW_WORK_TYPES)
def test_solo_maintainer_still_skips_only_review_request(defaults: dict, work_type: str) -> None:
    # solo-maintainer defers reviewer assignment but NOT thread resolution —
    # the unresolved-threads check stays blocking for solo maintainers.
    threads = _check_by_name(defaults[work_type]["checks"], "No unresolved review threads")
    assert "solo-maintainer" not in threads.get("modes", {})
