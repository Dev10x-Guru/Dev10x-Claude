"""Tests for opening, creating and resuming sessions from the page (GH-1722)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from dev10x.comm.supervisor import launcher
from dev10x.comm.supervisor.launcher import (
    Checkout,
    Launched,
    LaunchError,
    Project,
    agent_name,
    create_worktree,
    is_valid_branch,
    new_pane_id,
    open_session,
    read_project,
)

ROOT = "/work/dx/Dev10x-Claude"
OPEN_WT = "/work/.herdr/worktrees/Dev10x-Claude/open-one"
CLOSED_WT = "/work/.herdr/worktrees/Dev10x-Claude/closed-one"
PROJECT = Project(
    root=ROOT,
    name="Dev10x-Claude",
    main_workspace_id="w1P",
    checkouts=[
        Checkout(path=ROOT, branch="develop", is_main=True, workspace_id="w1P"),
        Checkout(path=OPEN_WT, branch="janusz/GH-1/a", is_main=False, workspace_id="w66"),
        Checkout(path=CLOSED_WT, branch="janusz/GH-2/b", is_main=False),
    ],
)
TAB = {"result": {"tab": {"tab_id": "w1P:t9"}, "root_pane": {"pane_id": "w1P:p9"}}}


class FakeHerdr:
    def __init__(self, *, replies: dict[str, Any] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args[1:])
        reply = self.replies.get(" ".join(args[1:3]), {"result": {}})
        if isinstance(reply, subprocess.CompletedProcess):
            return reply
        if isinstance(reply, Exception):
            raise reply
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(reply))


@pytest.fixture(autouse=True)
def fixed_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.secrets, "token_hex", lambda n: "beef")


class TestReadProject:
    def test_maps_herdr_worktrees(self) -> None:
        herdr = FakeHerdr(
            replies={
                "worktree list": {
                    "result": {
                        "source": {
                            "repo_root": ROOT,
                            "repo_name": "Dev10x-Claude",
                            "source_workspace_id": "w1P",
                        },
                        "worktrees": [
                            {"path": ROOT, "branch": "develop", "open_workspace_id": "w1P"},
                            {
                                "path": OPEN_WT,
                                "branch": "janusz/GH-1/a",
                                "is_linked_worktree": True,
                                "open_workspace_id": "w66",
                            },
                            {
                                "path": CLOSED_WT,
                                "branch": "janusz/GH-2/b",
                                "is_linked_worktree": True,
                            },
                            {"path": "/gone", "is_linked_worktree": True, "is_prunable": True},
                            "junk",
                        ],
                    }
                }
            }
        )

        assert read_project(root=OPEN_WT, runner=herdr) == PROJECT

    def test_falls_back_to_the_folder_name(self) -> None:
        project = read_project(root="/work/x/repo", runner=FakeHerdr())

        assert (project.root, project.name, project.checkouts) == ("/work/x/repo", "repo", [])


class TestOpenSession:
    @pytest.mark.parametrize(
        ("path", "workspace"),
        [(ROOT, "w1P"), (OPEN_WT, "w66")],
        ids=["main-folder", "open-worktree"],
    )
    def test_open_checkout_gets_a_new_tab(self, path: str, workspace: str) -> None:
        herdr = FakeHerdr(replies={"tab create": TAB})

        launched = open_session(project=PROJECT, path=path, runner=herdr)

        assert (herdr.calls, launched) == (
            [
                ["tab", "create", "--workspace", workspace, "--cwd", path, "--no-focus"],
                [
                    "agent",
                    "start",
                    f"{path.rsplit('/', 1)[-1].lower()}-beef",
                    "--kind",
                    "claude",
                    "--pane",
                    "w1P:p9",
                ],
            ],
            Launched(pane_id="w1P:p9", agent=f"{path.rsplit('/', 1)[-1].lower()}-beef", path=path),
        )

    def test_closed_worktree_opens_as_usual_and_resumes(self) -> None:
        herdr = FakeHerdr(replies={"worktree open": {"result": {"pane": {"pane_id": "w9:p1"}}}})

        open_session(project=PROJECT, path=CLOSED_WT, resume="sid-old", runner=herdr)

        assert herdr.calls == [
            ["worktree", "open", "--cwd", ROOT, "--path", CLOSED_WT, "--no-focus"],
            [
                "agent",
                "start",
                "closed-one-beef",
                "--kind",
                "claude",
                "--pane",
                "w9:p1",
                "--",
                "--resume",
                "sid-old",
            ],
        ]

    def test_main_folder_without_a_workspace_gets_one(self) -> None:
        project = Project(
            root=ROOT,
            name="x",
            main_workspace_id="",
            checkouts=[Checkout(path=ROOT, branch="develop", is_main=True)],
        )
        herdr = FakeHerdr(
            replies={"workspace create": {"result": {"root_pane": {"pane_id": "w2:p1"}}}}
        )

        open_session(project=project, path=ROOT, runner=herdr)

        assert herdr.calls[0] == ["workspace", "create", "--cwd", ROOT, "--no-focus"]

    def test_refuses_a_folder_outside_the_project(self) -> None:
        with pytest.raises(LaunchError, match="not a checkout"):
            open_session(project=PROJECT, path="/etc", runner=FakeHerdr())


class TestCreateWorktree:
    def test_creates_then_starts_claude(self) -> None:
        herdr = FakeHerdr(
            replies={
                "worktree create": {
                    "result": {
                        "workspace": {"workspace_id": "w7"},
                        "worktree": {"path": "/wt/new-thing"},
                        "root_pane": {"pane_id": "w7:p1"},
                    }
                }
            }
        )

        launched = create_worktree(project=PROJECT, branch="janusz/GH-9/new-thing", runner=herdr)

        assert (herdr.calls[0], launched) == (
            [
                "worktree",
                "create",
                "--cwd",
                ROOT,
                "--branch",
                "janusz/GH-9/new-thing",
                "--no-focus",
            ],
            Launched(pane_id="w7:p1", agent="new-thing-beef", path="/wt/new-thing"),
        )

    @pytest.mark.parametrize("branch", ["", "a..b", "/x", "x/", "has space", "a//b"])
    def test_refuses_a_bad_branch(self, branch: str) -> None:
        with pytest.raises(LaunchError, match="not a usable branch"):
            create_worktree(project=PROJECT, branch=branch, runner=FakeHerdr())


class TestHerdrFailures:
    @pytest.mark.parametrize(
        ("reply", "message"),
        [
            (FileNotFoundError("herdr"), "not installed"),
            (subprocess.TimeoutExpired(cmd="herdr", timeout=60), "please try again"),
            (
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no shell"),
                "failed: no shell",
            ),
            (
                subprocess.CompletedProcess(args=[], returncode=0, stdout="not json"),
                "invalid JSON",
            ),
        ],
        ids=["missing", "timeout", "exit-code", "bad-json"],
    )
    def test_reported_as_launch_errors(self, reply: Any, message: str) -> None:
        herdr = FakeHerdr(replies={"tab create": reply})

        with pytest.raises(LaunchError, match=message):
            open_session(project=PROJECT, path=ROOT, runner=herdr)

    def test_non_object_reply_has_no_pane(self) -> None:
        herdr = FakeHerdr(
            replies={"tab create": subprocess.CompletedProcess(args=[], returncode=0, stdout="[]")}
        )

        with pytest.raises(LaunchError, match="did not report the new pane"):
            open_session(project=PROJECT, path=ROOT, runner=herdr)


@pytest.mark.parametrize(
    ("payload", "pane"),
    [
        ({"result": {"root_pane": {"pane_id": "a"}}}, "a"),
        ({"result": {"pane": {"pane_id": "b"}}}, "b"),
        ({"result": {"workspace": {"panes": [{"pane_id": "c"}]}}}, "c"),
        ({"root_pane": {"pane_id": "d"}}, "d"),
    ],
)
def test_new_pane_id(payload: dict[str, Any], pane: str) -> None:
    assert new_pane_id(payload=payload) == pane


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("Supervisor Status_Bar", "supervisor-status_bar-beef"),
        ("1722-fix", "s-1722-fix-beef"),
        ("x" * 50, f"{'x' * 28}-beef"),
    ],
)
def test_agent_name_is_a_valid_herdr_name(hint: str, expected: str) -> None:
    assert agent_name(hint=hint) == expected


@pytest.mark.parametrize(("branch", "ok"), [("janusz/GH-1/x", True), ("x.y", True), ("x.", False)])
def test_is_valid_branch(branch: str, ok: bool) -> None:
    assert is_valid_branch(branch=branch) is ok
