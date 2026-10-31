"""Tests for naming sessions after their branch (GH-1722)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dev10x.comm.supervisor.naming import (
    Rename,
    is_default_name,
    is_valid_name,
    name_from_branch,
    plan_renames,
)
from dev10x.comm.supervisor.sessions import SessionView
from dev10x.comm.supervisor.workspace import Workspace

WT = "/work/.herdr/worktrees/Dev10x-Claude/janusz-supervisor-daemon-poc"
VIEW = SessionView(
    session_id="sid-1",
    name="janusz-supervisor-daemon-poc-41",
    cwd=WT,
    status="idle",
    waiting_for="",
    pane_id="w1:p1",
    callsign="",
    summary="",
    board_state="",
    group="done",
)
WORKSPACES = {
    WT: Workspace(project="Dev10x-Claude", root=WT, branch="janusz/GH-1722/supervisor-status-bar")
}


class TestIsDefaultName:
    @pytest.mark.parametrize(
        ("name", "cwd", "expected"),
        [
            ("tt-dealeradmin-2a", "/work/tt/tt-dealeradmin", True),
            ("janusz-supervisor-daemon-poc-41", WT, True),
            ("gpv-di-report", "/work/tt/tt-pos", False),
            ("tt-pos-zz", "/work/tt/tt-pos", False),
            ("tt-pos-2a-x", "/work/tt/tt-pos", False),
            ("anything-2a", "", False),
        ],
    )
    def test_detects_generated_names(self, name: str, cwd: str, expected: bool) -> None:
        assert is_default_name(name=name, cwd=cwd) is expected


class TestNameFromBranch:
    @pytest.mark.parametrize(
        ("branch", "expected"),
        [
            ("janusz/GH-1722/supervisor-status-bar", "GH-1722-supervisor-status-bar"),
            ("janusz/PAY-12/wt-3/fix-tax", "PAY-12-fix-tax"),
            (
                "janusz/TD-6636/janusz-c4-ftp-feed-intake/show-supplier-feed-request",
                "TD-6636-show-supplier-feed-request",
            ),
            ("janusz/GH-103/read-side-adr", "GH-103-read-side-adr"),
            ("feature-x", "feature-x"),
            ("janusz/fix: odd chars!", "fix-odd-chars"),
            ("main", ""),
            ("HEAD", ""),
            ("", ""),
            ("u/" + "a" * 80, "a" * 64),
        ],
    )
    def test_drops_the_user_and_flattens(self, branch: str, expected: str) -> None:
        assert name_from_branch(branch=branch) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("GH-1-x", True), ("a.b_c", True), ("-lead", False), ("has space", False), ("x" * 65, False)],
)
def test_is_valid_name(name: str, expected: bool) -> None:
    assert is_valid_name(name=name) is expected


class TestPlanRenames:
    def test_renames_an_idle_default_named_session(self) -> None:
        assert plan_renames(sessions=[VIEW], workspaces=WORKSPACES) == [
            Rename(session=VIEW, name="GH-1722-supervisor-status-bar")
        ]

    @pytest.mark.parametrize(
        "view",
        [
            replace(VIEW, status="busy"),
            replace(VIEW, status="waiting"),
            replace(VIEW, pane_id=""),
            replace(VIEW, name="chosen-by-hand"),
            replace(VIEW, cwd="/elsewhere/janusz-supervisor-daemon-poc"),
        ],
        ids=["busy", "waiting", "no-pane", "hand-named", "no-workspace"],
    )
    def test_leaves_others_alone(self, view: SessionView) -> None:
        assert plan_renames(sessions=[view], workspaces=WORKSPACES) == []

    def test_never_takes_a_name_already_in_use(self) -> None:
        twin = replace(VIEW, session_id="sid-2", name="janusz-supervisor-daemon-poc-5a")
        holder = replace(VIEW, session_id="sid-3", name="GH-1722-supervisor-status-bar")

        assert plan_renames(sessions=[VIEW, twin, holder], workspaces=WORKSPACES) == []

    def test_two_sessions_in_one_worktree_get_one_rename(self) -> None:
        twin = replace(VIEW, session_id="sid-2", name="janusz-supervisor-daemon-poc-5a")

        assert [
            rename.session.session_id
            for rename in plan_renames(sessions=[VIEW, twin], workspaces=WORKSPACES)
        ] == ["sid-1"]
