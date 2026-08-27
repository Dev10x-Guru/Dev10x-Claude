"""Persist and report the project's issue-tracker choice (GH-768).

The write half of tracker-aware seeding: the onboarding tracker-choice
gate calls :func:`pin_tracker` once, and every later ``ensure-base`` /
``seed_worktree`` run reads the answer back through
:mod:`dev10x.skills.permission.tracker_resolve`.

Keyed by the repo stem from the git **common dir**, so a choice made
inside ``<repo>-3`` also covers ``<repo>`` and a ``<repo>-9`` created
next month — the same identity :func:`~dev10x.session.preset_pin.
pin_preset` uses, via the shared
:func:`~dev10x.session.preset_pin.pin_project_prefs` writer.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.common.tracker_choice import Tracker, parse_tracker
from dev10x.domain.documents.session_yaml import FrictionYamlDocument
from dev10x.session.preset_pin import (
    pin_project_prefs,
    probe_path,
    resolve_repo_identity,
)

TRACKER_VALUES: tuple[str, ...] = tuple(tracker.value for tracker in Tracker)


def pin_tracker(
    *,
    tracker: str,
    scope: str = "repo",
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """Persist the project's tracker into the global ``friction.yaml``.

    Idempotent — an entry already covering this checkout is replaced,
    never duplicated. An unrecognised tracker fails loud here rather
    than silently degrading to the default at the next seeding run,
    when the connection to the typo would be long lost.
    """
    parsed = parse_tracker(tracker)
    if parsed is None:
        return err(f"unknown tracker {tracker!r}; expected one of {list(TRACKER_VALUES)}")
    return pin_project_prefs(prefs={"tracker": parsed.value}, scope=scope, cwd=cwd)


def tracker_status(*, cwd: str | None = None) -> Result[dict[str, Any]]:
    """Report whether this repo has a durable tracker choice yet.

    Gate the onboarding tracker-choice question on ``pinned: false``:
    re-asking a settled workspace fact on every bootstrap is the
    friction the gate exists to remove.
    """
    identity_result = resolve_repo_identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    document = FrictionYamlDocument(toplevel=probe_path(identity))
    matched = document.matched() or {}
    pinned = parse_tracker(matched.get("tracker"))
    fallback = parse_tracker(document.defaults().get("tracker"))
    resolved = pinned or fallback or Tracker.default()
    return ok(
        {
            "pinned": pinned is not None,
            "tracker": resolved.value,
            "source": "project" if pinned else ("defaults" if fallback else "default"),
            "repo_name": identity["name"],
            "repo_root": identity["root"],
            "choices": list(TRACKER_VALUES),
        }
    )


__all__ = ["TRACKER_VALUES", "pin_tracker", "tracker_status"]
