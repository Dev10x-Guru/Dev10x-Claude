"""Tests for the supervisor HTML page (GH-1692)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dev10x.comm.supervisor.decisions import Decision
from dev10x.comm.supervisor.page import render_page
from dev10x.comm.supervisor.probes import Snapshot
from dev10x.comm.supervisor.sessions import SessionView
from tests.comm.supervisor.conftest import NOW

TOKEN = "tok-123"


def view(**overrides: str) -> SessionView:
    base = SessionView(
        session_id="sid-1",
        name="kb-84",
        cwd="/home/janusz/KB",
        status="idle",
        waiting_for="",
        pane_id="w3:p1",
        callsign="",
        summary="",
        board_state="",
        group="done",
    )
    return replace(base, **overrides)


def decision(**overrides: object) -> Decision:
    base = Decision(
        decision_id="sid-1-abcd",
        session_id="sid-1",
        cwd="/w",
        question="Which hub?",
        header="Hub",
        options=["Relay", "mc-updates"],
        multi_select=False,
        created="2026-10-31T12:00:00+00:00",
    )
    return replace(base, **overrides)


def render(
    *, views: list[SessionView], decisions: list[Decision] | None = None, **kw: object
) -> str:
    return render_page(
        snapshot=Snapshot(sessions=views, errors=kw.get("errors", {}), taken_at=NOW),  # type: ignore[arg-type]
        decisions=decisions or [],
        pane_text=kw.get("pane_text", {}),  # type: ignore[arg-type]
        token=TOKEN,
    )


class TestRenderPage:
    def test_escapes_peer_text(self) -> None:
        html = render(
            views=[view(summary="<script>alert(1)</script>", name="a&b")],
            decisions=[decision(question="<b>x</b>", options=["<i>y</i>"])],
        )

        assert (
            "<script>alert" in html,
            "&lt;script&gt;alert(1)" in html,
            "&lt;i&gt;y" in html,
        ) == (
            False,
            True,
            True,
        )

    def test_groups_needs_you_first(self) -> None:
        html = render(
            views=[
                view(session_id="a", name="busy-one", status="busy", group="working"),
                view(session_id="b", name="stuck-one", status="waiting", group="needs-you"),
            ]
        )

        assert html.index("Needs you (1)") < html.index("stuck-one") < html.index("Working (1)")

    def test_shows_exact_keys_for_permission_prompt(self) -> None:
        html = render(
            views=[view(status="waiting", waiting_for="permission prompt", group="needs-you")],
            pane_text={"sid-1": "Allow Bash(rm -rf build)?"},
        )

        assert (
            "Send 1 (allow)" in html,
            "Send esc (deny)" in html,
            "Allow Bash(rm -rf build)?" in html,
        ) == (True, True, True)

    def test_decision_buttons_post_option_index(self) -> None:
        html = render(views=[view(status="waiting", group="needs-you")], decisions=[decision()])

        assert (
            'name="option_index" value="1"' in html,
            ">mc-updates</button>" in html,
            f'name="token" value="{TOKEN}"' in html,
        ) == (True, True, True)

    def test_prose_question_offers_reply(self) -> None:
        html = render(
            views=[view(board_state="needs-input", group="needs-you", summary="Pick A or B?")],
            pane_text={"sid-1": "last lines"},
        )

        assert ('action="/reply"' in html, "last lines" in html) == (True, True)

    @pytest.mark.parametrize("group", ["working", "done"])
    def test_no_reply_box_outside_needs_you(self, group: str) -> None:
        assert 'action="/reply"' not in render(views=[view(group=group)])

    def test_callsign_and_waiting_label(self) -> None:
        html = render(
            views=[
                view(
                    callsign="login fix", waiting_for="input needed", group="needs-you", pane_id=""
                )
            ]
        )

        assert ("login fix [kb-84]" in html, "input needed" in html) == (True, True)

    def test_probe_errors_shown(self) -> None:
        html = render(views=[], errors={"herdr": "herdr is not installed"})

        assert "herdr: herdr is not installed" in html

    def test_reload_skips_while_typing(self) -> None:
        assert "location.reload" in render(views=[])
