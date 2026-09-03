"""Regression tests for the verify-acc-dod default checks (GH-736).

A skill-audit caught the work-on completion gate offering "Work complete
(Recommended)" while the "No unresolved review threads" check was failing
after the supervisor had explicitly *deferred* review threads. The honest
fix is for the ``review-deferred`` mode to skip the unresolved-threads
check (so the DoD reflects the agreed scope) — not to paper over a red
check with gate framing.

These tests pin the ``modes`` mapping on the relevant checks so the
``review-deferred`` contract cannot silently regress.

GH-1172 adds a second concern: the skill collapsed its
``friction_level``-keyed behaviour table to a single baseline. The
tests below pin what MUST survive that collapse — the merge-gated
completion matrix stays sourced from
``completion_gate_recommendation()``, and the resolver /
recommendation boundary stays documented rather than merged away.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.session_rules import (
    CompletionRecommendation,
    completion_gate_recommendation,
)

SKILL_DIR = Path(__file__).resolve().parents[3] / "skills" / "verify-acc-dod"
DEFAULTS = SKILL_DIR / "references" / "defaults.yaml"
SKILL_MD = SKILL_DIR / "SKILL.md"

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
def test_fixes_scope_delivery_check_present(defaults: dict, work_type: str) -> None:
    # GH-856: a Fixes:/Closes: link auto-closes its issue on merge
    # regardless of delivered scope. The prompt check blocks a
    # short-closing merge, including self-disclosed cuts.
    check = _check_by_name(defaults[work_type]["checks"], "Fixes-linked issue scope delivered")
    assert check["check"] == "prompt"
    assert "Fixes" in check["prompt"]


@pytest.fixture(scope="module")
def skill_body() -> str:
    return SKILL_MD.read_text()


@pytest.mark.parametrize("source", [DEFAULTS, SKILL_MD], ids=["defaults", "skill"])
def test_no_friction_level_key_remains(source: Path) -> None:
    # GH-1172 acceptance: this layer reads no friction level at all. A
    # `friction_level:` key anywhere in the skill or its defaults would
    # reintroduce the per-level behaviour table the ticket collapsed.
    assert "friction_level" not in source.read_text()


def test_manual_checks_are_converted_not_asked(skill_body: str) -> None:
    # The single baseline is the old `adaptive` row: a `manual` item is a
    # judgement Claude makes from session context, never a per-item
    # AskUserQuestion that only fired at strict/guided.
    assert "converted to a `prompt` check" in skill_body
    assert "no per-item `AskUserQuestion`" in skill_body


def test_merge_gated_matrix_defers_to_domain_function(skill_body: str) -> None:
    # GH-729 must survive the collapse, and it must survive it in ONE
    # place: the skill documents the matrix but sources it from the
    # domain function rather than re-deriving it.
    assert "completion_gate_recommendation()" in skill_body
    for recommendation in ("Work complete", "Monitor for review", "Go back"):
        assert recommendation in skill_body


@pytest.mark.parametrize(
    "has_associated_pr,pr_merged,blocking_checks_pass,expected",
    [
        (True, True, True, CompletionRecommendation.WORK_COMPLETE),
        (False, False, True, CompletionRecommendation.WORK_COMPLETE),
        (True, False, True, CompletionRecommendation.MONITOR_REVIEW),
        (True, True, False, CompletionRecommendation.GO_BACK),
    ],
)
def test_merge_gated_recommendation_unchanged_by_collapse(
    has_associated_pr: bool,
    pr_merged: bool,
    blocking_checks_pass: bool,
    expected: CompletionRecommendation,
) -> None:
    # The friction table is gone; the recommendation it used to sit
    # beside is not. A merged PR with a red blocking check still routes
    # to Go back — the collapse must not have widened "done".
    assert (
        completion_gate_recommendation(
            has_associated_pr=has_associated_pr,
            pr_merged=pr_merged,
            blocking_checks_pass=blocking_checks_pass,
        )
        is expected
    )


def test_resolver_recommendation_boundary_documented(skill_body: str) -> None:
    # ADR-0016: resolve_gate decides whether the gate FIRES; this skill
    # decides what it RECOMMENDS. Collapsing the friction table must not
    # collapse these two into one decision.
    assert "resolver decides whether the gate FIRES" in skill_body
    assert "skill decides what the gate RECOMMENDS" in skill_body
    assert "mcp__plugin_Dev10x_cli__resolve_gate" in skill_body
    for effect in ("`effect: ask`", "`effect: auto-advance`", "`effect: skip`"):
        assert effect in skill_body


@pytest.mark.parametrize("work_type", REVIEW_WORK_TYPES)
def test_solo_maintainer_still_skips_only_review_request(defaults: dict, work_type: str) -> None:
    # solo-maintainer defers reviewer assignment but NOT thread resolution —
    # the unresolved-threads check stays blocking for solo maintainers.
    threads = _check_by_name(defaults[work_type]["checks"], "No unresolved review threads")
    assert "solo-maintainer" not in threads.get("modes", {})
