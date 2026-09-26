"""A stand-down answer holds until the task list changes (GH-1470).

Field report: after "Stand down", the all-complete gate re-fired after
each of the next three plain Q&A answers. Standby is scoped to the
supervisor's next message, which is exactly what a follow-up question
is, so stand-down needs a lifetime of its own — the task set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.hooks.session_dispatch import build_stop_verdict
from dev10x.hooks.stop_verdict import (
    StopSignal,
    _stand_down_path,
    clear_stand_down,
    decide,
    read_stand_down,
    record_stand_down,
    task_fingerprint,
)

from .conftest import DEPLETED_PLAN, PENDING_PLAN

_STAND_DOWN_ANSWER = (
    'User has answered your questions: "Anything open?"="Stand down — the work is complete".'
)

_COMPLETED = {"tasks": [{"id": "1", "subject": "Ship it", "status": "completed"}]}
_REOPENED = {"tasks": [{"id": "1", "subject": "Ship it", "status": "in_progress"}]}
_EXTENDED = {
    "tasks": [
        {"id": "1", "subject": "Ship it", "status": "completed"},
        {"id": "2", "subject": "Follow-up fix", "status": "pending"},
    ]
}


def _user(*, uuid: str, content: object) -> dict:
    return {"type": "user", "uuid": uuid, "message": {"role": "user", "content": content}}


def _answered(*, uuid: str = "a1", text: str = _STAND_DOWN_ANSWER) -> dict:
    return _user(
        uuid=uuid,
        content=[{"type": "tool_result", "content": [{"type": "text", "text": text}]}],
    )


def _said(*, text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _transcript(*, tmp_path: Path, name: str, entries: list[dict]) -> str:
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return str(path)


@pytest.fixture()
def stand_down_turn(tmp_path: Path) -> str:
    return _transcript(
        tmp_path=tmp_path,
        name="stand-down",
        entries=[_user(uuid="u1", content="wrap up"), _answered(), _said(text="Standing down.")],
    )


@pytest.fixture()
def follow_up_turn(tmp_path: Path) -> str:
    """A plain question typed after the stand-down, and its answer."""
    return _transcript(
        tmp_path=tmp_path,
        name="follow-up",
        entries=[
            _user(uuid="u2", content="quick one: which file held the fix?"),
            _said(text="src/dev10x/hooks/stop_verdict.py."),
        ],
    )


class TestTheAnswerIsRecorded:
    def test_the_answering_turn_ends_quietly(
        self, stand_down_turn: str, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={"session_id": "sd1", "transcript_path": stand_down_turn}, plan=_COMPLETED
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.STOOD_DOWN

    def test_it_asks_for_the_task_set_to_be_persisted(
        self, stand_down_turn: str, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={"session_id": "sd2", "transcript_path": stand_down_turn}, plan=_COMPLETED
        )

        assert verdict.record_stand_down == task_fingerprint(plan=_COMPLETED)

    def test_decide_itself_writes_no_marker(
        self, stand_down_turn: str, isolated_markers: Path
    ) -> None:
        """The rule reads markers and never writes them; the wiring does."""
        decide(data={"session_id": "sd3", "transcript_path": stand_down_turn}, plan=_COMPLETED)

        assert not (isolated_markers / "sd3.standdown").exists()

    def test_a_question_that_merely_mentions_standing_down_is_not_one(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Only the answer side counts — this answer outlives the turn."""
        transcript = _transcript(
            tmp_path=tmp_path,
            name="mention",
            entries=[
                _user(uuid="u1", content="status?"),
                _answered(text='"Stand down, or keep going?"="Keep going".'),
                _said(text="Carrying on."),
            ],
        )

        verdict = decide(
            data={"session_id": "sd4", "transcript_path": transcript}, plan=DEPLETED_PLAN
        )

        assert verdict.signal == StopSignal.BLOCKED


class TestItHoldsUntilTheTaskSetChanges:
    def test_a_later_question_with_the_same_list_ends_without_a_block(
        self, follow_up_turn: str, isolated_markers: Path
    ) -> None:
        record_stand_down(session_id="hold1", fingerprint=task_fingerprint(plan=_COMPLETED))

        verdict = decide(
            data={"session_id": "hold1", "transcript_path": follow_up_turn}, plan=_COMPLETED
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.STOOD_DOWN
        assert verdict.clear_stand_down is False

    def test_a_new_task_re_arms_the_gate(
        self, follow_up_turn: str, isolated_markers: Path
    ) -> None:
        record_stand_down(session_id="hold2", fingerprint=task_fingerprint(plan=_COMPLETED))

        verdict = decide(
            data={"session_id": "hold2", "transcript_path": follow_up_turn}, plan=_EXTENDED
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.CONTINUE
        assert verdict.clear_stand_down is True

    def test_a_status_change_re_arms_the_gate(
        self, follow_up_turn: str, isolated_markers: Path
    ) -> None:
        record_stand_down(session_id="hold3", fingerprint=task_fingerprint(plan=_COMPLETED))

        verdict = decide(
            data={"session_id": "hold3", "transcript_path": follow_up_turn}, plan=_REOPENED
        )

        assert verdict.signal == StopSignal.CONTINUE
        assert verdict.clear_stand_down is True

    def test_without_a_marker_nothing_is_cleared(
        self, follow_up_turn: str, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={"session_id": "hold4", "transcript_path": follow_up_turn}, plan=_COMPLETED
        )

        assert verdict.signal == StopSignal.BLOCKED
        assert verdict.clear_stand_down is False


class TestTheFingerprint:
    def test_task_order_does_not_change_it(self) -> None:
        reordered = {"tasks": list(reversed(_EXTENDED["tasks"]))}

        assert task_fingerprint(plan=reordered) == task_fingerprint(plan=_EXTENDED)

    @pytest.mark.parametrize(
        "changed",
        [_REOPENED, _EXTENDED],
        ids=["status", "new-task"],
    )
    def test_a_changed_set_changes_it(self, changed: dict) -> None:
        assert task_fingerprint(plan=changed) != task_fingerprint(plan=_COMPLETED)

    def test_a_task_without_an_id_is_keyed_by_subject(self) -> None:
        renamed = {"tasks": [{"subject": "Other", "status": "completed"}]}

        assert task_fingerprint(plan=renamed) != task_fingerprint(plan=DEPLETED_PLAN)

    def test_no_plan_still_fingerprints(self) -> None:
        assert task_fingerprint(plan=None) == task_fingerprint(plan={})


class TestTheMarkerDegradesQuietly:
    def test_round_trip(self, isolated_markers: Path) -> None:
        record_stand_down(session_id="m1", fingerprint="abc")

        assert read_stand_down(session_id="m1") == "abc"

    def test_an_absent_marker_is_no_stand_down(self, isolated_markers: Path) -> None:
        assert read_stand_down(session_id="m2") is None

    @pytest.mark.parametrize(
        "content",
        ["{not json", "[1, 2]", '{"fingerprint": 7}', '{"fingerprint": ""}'],
        ids=["corrupt", "not-a-mapping", "not-a-string", "empty"],
    )
    def test_an_unusable_marker_is_no_stand_down(
        self, isolated_markers: Path, content: str
    ) -> None:
        isolated_markers.mkdir(parents=True, exist_ok=True)
        (isolated_markers / "m3.standdown").write_text(content, encoding="utf-8")

        assert read_stand_down(session_id="m3") is None

    def test_a_corrupt_marker_is_named(
        self, isolated_markers: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        isolated_markers.mkdir(parents=True, exist_ok=True)
        (isolated_markers / "m4.standdown").write_text("{not json", encoding="utf-8")

        read_stand_down(session_id="m4")

        assert "reading the stand-down marker" in capsys.readouterr().err

    def test_an_unwritable_marker_is_named(
        self,
        isolated_markers: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def refuse(*args: object, **kwargs: object) -> None:
            raise OSError("read-only file system")

        monkeypatch.setattr("dev10x.hooks.stop_verdict.atomic_write_text", refuse)

        record_stand_down(session_id="m5", fingerprint="abc")

        assert "writing the stand-down marker" in capsys.readouterr().err

    def test_clearing_removes_it(self, isolated_markers: Path) -> None:
        record_stand_down(session_id="m6", fingerprint="abc")

        clear_stand_down(session_id="m6")

        assert read_stand_down(session_id="m6") is None

    def test_a_failed_clear_is_named(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class _Stuck:
            def unlink(self, *, missing_ok: bool) -> None:
                raise OSError("permission denied")

        monkeypatch.setattr(
            "dev10x.hooks.stop_verdict._stand_down_path", lambda *, session_id: _Stuck()
        )

        clear_stand_down(session_id="m7")

        assert "clearing the stand-down marker" in capsys.readouterr().err


class TestTheRealStandDownPath:
    def test_it_sits_beside_the_standby_marker(self) -> None:
        path = _stand_down_path(session_id="alpha")

        assert path.name == "alpha.standdown"
        assert path.parent == Path("/tmp/Dev10x/stop-verdict")

    def test_a_session_without_an_id_still_has_a_path(self) -> None:
        assert _stand_down_path(session_id="").name == "unknown.standdown"


class TestTheWiringPersistsAndClears:
    @pytest.fixture()
    def plan_on_disk(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        """A mutable stand-in for the persisted plan the wiring reads."""
        current: dict = {"summary": {"plan": {"status": "in_progress"}, **_COMPLETED}}
        monkeypatch.setattr("dev10x.hooks.session_dispatch._get_toplevel", lambda: "/repo")
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch._current_branch", lambda *, toplevel: None
        )
        monkeypatch.setattr(
            "dev10x.hooks.session_dispatch.read_plan_summary",
            lambda *, toplevel: current["summary"],
        )
        return current

    def test_stand_down_then_follow_up_then_new_task(
        self,
        stand_down_turn: str,
        follow_up_turn: str,
        isolated_markers: Path,
        plan_on_disk: dict,
    ) -> None:
        answered = build_stop_verdict(
            data={"session_id": "w1", "transcript_path": stand_down_turn}
        )
        followed_up = build_stop_verdict(
            data={"session_id": "w1", "transcript_path": follow_up_turn}
        )
        plan_on_disk["summary"] = {"plan": {"status": "in_progress"}, **PENDING_PLAN}
        re_armed = build_stop_verdict(data={"session_id": "w1", "transcript_path": follow_up_turn})

        assert answered is None
        assert followed_up is None
        assert re_armed is not None
        assert re_armed.signal == StopSignal.CONTINUE
        assert read_stand_down(session_id="w1") is None

    def test_the_audit_record_names_the_branch(
        self,
        stand_down_turn: str,
        isolated_markers: Path,
        plan_on_disk: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        recorded: dict[str, str] = {}

        def capture(*, rule_id: str, reason: str, extra: dict | None = None) -> None:
            recorded.update(rule_id=rule_id, reason=reason, **(extra or {}))

        monkeypatch.setattr("dev10x.hooks.session_dispatch.set_decision_attribution", capture)

        build_stop_verdict(data={"session_id": "w2", "transcript_path": stand_down_turn})

        assert recorded["signal"] == StopSignal.STOOD_DOWN
