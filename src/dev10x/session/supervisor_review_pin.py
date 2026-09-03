"""Persist the project's supervisor-review posture (ADR-0022 D-2, GH-1165).

The write half of the review-boundary fact: `Dev10x:friction-setup` /
`Dev10x:onboarding` call :func:`pin_supervisor_review` once, and every gate
resolution reads the answer back through
:func:`dev10x.mcp.gate_tools.supervisor_review_status` (which already
existed before this module, GH-1161/PR #1176 — this adds the missing
write half and folds a `pinned` signal into that reader).

Keyed by the repo stem from the git **common dir**, so a choice made
inside ``<repo>-3`` also covers ``<repo>`` and a ``<repo>-9`` created next
month — the same identity :func:`~dev10x.session.preset_pin.pin_preset`
and :func:`~dev10x.session.tracker_pin.pin_tracker` use, via the shared
:func:`~dev10x.session.preset_pin.pin_project_prefs` writer.

``supervisor_review`` is a project-wide fact, not a per-gate toggle (it is
deliberately absent from
:data:`dev10x.domain.gate_policy._ENUM_TOGGLES`), so it cannot be set
through :func:`~dev10x.session.preset_pin.pin_preset`'s ``gate_overrides``
— it needs its own writer, mirroring :mod:`dev10x.session.tracker_pin`
rather than the preset/overlay pin.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.result import Result, err
from dev10x.domain.gate_policy import (
    SUPERVISOR_REVIEW_NONE,
    SUPERVISOR_REVIEW_REQUIRED,
)
from dev10x.session.preset_pin import pin_project_prefs

SUPERVISOR_REVIEW_VALUES: tuple[str, ...] = (
    SUPERVISOR_REVIEW_REQUIRED,
    SUPERVISOR_REVIEW_NONE,
)


def pin_supervisor_review(
    *,
    supervisor_review: str,
    scope: str = "repo",
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """Persist the project's supervisor-review posture into ``friction.yaml``.

    Idempotent — an entry already covering this checkout is replaced,
    never duplicated. An unrecognised value fails loud here rather than
    silently coercing to ``required`` at the next gate resolution, when
    the connection to the typo would be long lost — the same contract
    :func:`~dev10x.session.tracker_pin.pin_tracker` applies to an
    unrecognised tracker.
    """
    if supervisor_review not in SUPERVISOR_REVIEW_VALUES:
        return err(
            f"unknown supervisor_review {supervisor_review!r}; "
            f"expected one of {list(SUPERVISOR_REVIEW_VALUES)}"
        )
    return pin_project_prefs(prefs={"supervisor_review": supervisor_review}, scope=scope, cwd=cwd)


__all__ = [
    "SUPERVISOR_REVIEW_VALUES",
    "pin_supervisor_review",
]
