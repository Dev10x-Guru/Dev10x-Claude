"""Shared fixtures for the hook tests.

``test_stop_verdict.py`` and ``test_stop_verdict_audience.py`` both
drive :func:`dev10x.hooks.stop_verdict.decide`, so they need the same
two things: the audit attribution slot emptied around each test, and
both on-disk markers pointed somewhere other than the real
``/tmp/Dev10x``. ``test_block_attribution.py`` needs the first of
those and used to declare its own copy.

The marker fixture patches ``_standby_path`` as well as
``_marker_path`` even for tests that only exercise the cooldown. A
fixture that isolates one marker and not the other is the shape that
lets a later test leak into the developer's real ``/tmp`` without
failing — so the superset is the safer default, and the extra patch
costs a test that never touches standby nothing.

The per-file ``_transcript`` helpers stay where they are: they are
pure functions over ``tmp_path`` holding no state that can leak
between tests, which is the problem a shared fixture solves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.hooks.audit_emit import clear_decision_attribution


@pytest.fixture(autouse=True)
def _clear_attribution() -> None:
    """Empty the audit attribution slot around every test.

    ``build_stop_verdict`` sets it on every outcome, and the slot is
    module-level state that only ``audit_hook`` consumes and clears.
    These tests call the feature without that wrapper, so a slot left
    set here would be folded into whichever wrapped record ran next.
    """
    clear_decision_attribution()
    yield
    clear_decision_attribution()


#: A task list that exists and holds nothing open. Since GH-1339 this is
#: the only state that blocks without a prose deferral, so a test about
#: blocking must say which emptiness it means.
DEPLETED_PLAN = {"tasks": [{"subject": "Ship it", "status": "completed"}]}

#: A task list with work still on it — the state that auto-advances.
PENDING_PLAN = {"tasks": [{"subject": "Monitor CI", "status": "pending"}]}


@pytest.fixture()
def isolated_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the cooldown, standby and stand-down markers at a temp dir."""
    marker_dir = tmp_path / "markers"
    monkeypatch.setattr(
        "dev10x.hooks.stop_verdict._marker_path",
        lambda *, session_id: marker_dir / f"{session_id or 'unknown'}.marker",
    )
    monkeypatch.setattr(
        "dev10x.hooks.stop_verdict._standby_path",
        lambda *, session_id: marker_dir / f"{session_id or 'unknown'}.standby",
    )
    monkeypatch.setattr(
        "dev10x.hooks.stop_verdict._stand_down_path",
        lambda *, session_id: marker_dir / f"{session_id or 'unknown'}.standdown",
    )
    return marker_dir
