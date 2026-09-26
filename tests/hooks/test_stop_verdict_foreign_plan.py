"""A persisted plan from another session is no evidence (GH-1470).

There is one plan per checkout. A session that never ran ``TaskCreate``
was judged against whatever an earlier session left behind — the field
report's "19/20 tasks completed" came from a plan on ``develop`` written
by a previous session — so the ``NO_TASK_LIST`` escape never triggered.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.hooks import session_dispatch
from dev10x.hooks.session_dispatch import build_stop_verdict
from dev10x.hooks.stop_verdict import (
    StopSignal,
    decide,
    plan_is_foreign,
    read_session_start,
)

_STARTED = "2026-09-26T10:00:00.000Z"


def _plan(
    *, branch: object = "feature", last_synced: object = "2026-09-26T11:00:00+00:00"
) -> dict:
    return {
        "plan": {"branch": branch, "last_synced": last_synced, "status": "in_progress"},
        "tasks": [{"id": "1", "subject": "Ship it", "status": "completed"}],
    }


def _write(*, tmp_path: Path, lines: list[str], name: str = "transcript") -> str:
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


@pytest.fixture()
def transcript(tmp_path: Path) -> str:
    entries = [
        {"type": "user", "timestamp": _STARTED, "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello."}]},
        },
    ]
    return _write(tmp_path=tmp_path, lines=[json.dumps(entry) for entry in entries])


class TestPlanIsForeign:
    def test_a_plan_on_another_branch_is_foreign(self) -> None:
        assert plan_is_foreign(
            plan=_plan(branch="develop"), session_started=None, current_branch="feature"
        )

    def test_a_plan_last_synced_before_the_session_began_is_foreign(self) -> None:
        stale = _plan(last_synced="2026-09-20T09:00:00+00:00")

        assert plan_is_foreign(plan=stale, session_started=_STARTED, current_branch="feature")

    def test_this_sessions_plan_is_not(self) -> None:
        assert not plan_is_foreign(
            plan=_plan(), session_started=_STARTED, current_branch="feature"
        )

    @pytest.mark.parametrize(
        ("plan", "session_started"),
        [
            (None, _STARTED),
            (_plan(last_synced=None), _STARTED),
            (_plan(last_synced="not a time"), _STARTED),
            (_plan(last_synced="2026-09-20T09:00:00+00:00"), None),
            ({"plan": "not a mapping", "tasks": []}, _STARTED),
        ],
        ids=["no-plan", "never-synced", "unparseable-sync", "unknown-start", "odd-metadata"],
    )
    def test_an_unknown_fact_is_not_evidence(
        self, plan: dict | None, session_started: str | None
    ) -> None:
        assert not plan_is_foreign(plan=plan, session_started=session_started, current_branch=None)

    def test_a_plan_that_records_no_branch_is_not_judged_on_it(self) -> None:
        """``session_stale`` reads an absent identity as stale; here it is unknown."""
        assert not plan_is_foreign(
            plan=_plan(branch=None), session_started=None, current_branch="feature"
        )

    def test_a_naive_timestamp_reads_as_utc(self) -> None:
        naive = _plan(last_synced="2026-09-26T09:59:59")

        assert plan_is_foreign(plan=naive, session_started=_STARTED, current_branch=None)


class TestDecide:
    def test_a_foreign_plan_ends_the_turn(self, transcript: str, isolated_markers: Path) -> None:
        verdict = decide(
            data={"session_id": "f1", "transcript_path": transcript},
            plan=_plan(branch="develop"),
            current_branch="feature",
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.FOREIGN_PLAN

    def test_this_sessions_depleted_plan_still_blocks(
        self, transcript: str, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={"session_id": "f2", "transcript_path": transcript},
            plan=_plan(),
            session_started=_STARTED,
            current_branch="feature",
        )

        assert verdict.signal == StopSignal.BLOCKED


class TestReadSessionStart:
    def test_the_first_stamped_entry_wins(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path=tmp_path,
            lines=[
                "{not json",
                json.dumps({"type": "summary"}),
                json.dumps(["not", "a", "mapping"]),
                json.dumps({"timestamp": " 2026-09-26T10:00:00Z "}),
                json.dumps({"timestamp": "2026-09-26T12:00:00Z"}),
            ],
        )

        assert read_session_start(transcript_path=path) == "2026-09-26T10:00:00Z"

    def test_a_transcript_without_stamps_has_no_start(self, tmp_path: Path) -> None:
        path = _write(tmp_path=tmp_path, lines=[json.dumps({"type": "summary"})])

        assert read_session_start(transcript_path=path) is None

    def test_an_empty_path_has_no_start(self) -> None:
        assert read_session_start(transcript_path="") is None

    def test_a_missing_transcript_is_named(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert read_session_start(transcript_path=str(tmp_path / "gone.jsonl")) is None
        assert "reading the transcript for its start" in capsys.readouterr().err

    def test_an_undecodable_transcript_has_no_start(self, tmp_path: Path) -> None:
        path = tmp_path / "binary.jsonl"
        path.write_bytes(b"\xff\xfe\x00garbage")

        assert read_session_start(transcript_path=str(path)) is None


class TestCurrentBranch:
    @pytest.mark.parametrize(
        ("reported", "expected"),
        [("feature", "feature"), ("unknown", None), ("HEAD", None)],
    )
    def test_only_a_named_branch_counts(
        self, monkeypatch: pytest.MonkeyPatch, reported: str, expected: str | None
    ) -> None:
        class _Git:
            def __init__(self, *, cwd: str) -> None:
                self.branch = reported

        monkeypatch.setattr(session_dispatch, "GitContext", _Git)

        assert session_dispatch._current_branch(toplevel="/repo") == expected


class TestTheWiring:
    def test_an_inherited_plan_never_blocks(
        self, transcript: str, isolated_markers: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A session that never created tasks is not judged on another's list."""
        recorded: dict[str, str] = {}

        def capture(*, rule_id: str, reason: str, extra: dict | None = None) -> None:
            recorded.update(rule_id=rule_id, reason=reason, **(extra or {}))

        monkeypatch.setattr(session_dispatch, "_get_toplevel", lambda: "/repo")
        monkeypatch.setattr(session_dispatch, "_current_branch", lambda *, toplevel: "feature")
        monkeypatch.setattr(
            session_dispatch,
            "read_plan_summary",
            lambda *, toplevel: _plan(branch="develop", last_synced="2026-09-20T09:00:00Z"),
        )
        monkeypatch.setattr(session_dispatch, "set_decision_attribution", capture)

        verdict = build_stop_verdict(data={"session_id": "f3", "transcript_path": transcript})

        assert verdict is None
        assert recorded["signal"] == StopSignal.FOREIGN_PLAN
