"""Tests for the Herdr roster grouping (GH-1984)."""

from __future__ import annotations

import pytest

from dev10x.herdr.roster import (
    RepoRoster,
    Roster,
    RosterParseError,
    build_roster,
    parse_agents,
    parse_workspaces,
)
from tests.herdr.factories import (
    AGENTS,
    K8S_ROOT,
    POS_ROOT,
    WORKSPACES,
    agent,
    agent_list,
    workspace,
    workspace_list,
)


def _roster(*, cwd: str = "", repo_root: str = "") -> Roster:
    return build_roster(
        workspaces=parse_workspaces(raw=WORKSPACES),
        agents=parse_agents(raw=AGENTS),
        cwd=cwd,
        repo_root=repo_root,
    )


def _repo(*, roster: Roster, name: str) -> RepoRoster:
    return next(repo for repo in roster.repos if repo.repo_name == name)


@pytest.fixture
def roster() -> Roster:
    return _roster()


@pytest.fixture
def pos(roster: Roster) -> RepoRoster:
    return _repo(roster=roster, name="tt-pos")


class TestParse:
    @pytest.mark.parametrize(
        ("parser", "raw"),
        [
            (parse_workspaces, "not json"),
            (parse_workspaces, '{"result": {}}'),
            (parse_agents, "not json"),
            (parse_agents, '{"result": null}'),
        ],
    )
    def test_unreadable_payload_raises(self, parser, raw: str) -> None:
        with pytest.raises(RosterParseError):
            parser(raw=raw)

    def test_entries_without_an_id_are_skipped(self) -> None:
        raw = workspace_list(workspace(workspace_id="", label="x", number=1), {"label": "y"})

        assert parse_workspaces(raw=raw) == []

    def test_agents_without_a_pane_are_skipped(self) -> None:
        raw = agent_list(agent(pane_id="", workspace_id="w1"), "noise")  # type: ignore[arg-type]

        assert parse_agents(raw=raw) == []


class TestGrouping:
    def test_repos_are_sorted_by_name(self, roster: Roster) -> None:
        assert [repo.repo_name for repo in roster.repos] == ["tt-k8s", "tt-pos"]

    def test_main_sessions_are_the_repo_checkout_panes(self, pos: RepoRoster) -> None:
        assert [session.pane_id for session in pos.main_sessions] == ["w1F:p1", "wX:p1"]

    def test_worktree_sessions_are_linked_checkouts(self, pos: RepoRoster) -> None:
        assert [session.pane_id for session in pos.worktree_sessions] == ["wB8:p1", "w3Q:p1"]

    def test_other_agent_kinds_are_left_out(self, pos: RepoRoster) -> None:
        panes = [session.pane_id for session in pos.main_sessions + pos.worktree_sessions]

        assert "wX:p2" not in panes

    def test_workspace_without_binding_is_unbound(self, roster: Roster) -> None:
        assert [(session.pane_id, session.role) for session in roster.unbound] == [
            ("w5J:p1", "unbound")
        ]

    def test_agent_in_unknown_workspace_is_unbound(self) -> None:
        result = build_roster(
            workspaces=[],
            agents=parse_agents(raw=agent_list(agent(pane_id="w9:p1", workspace_id="w9"))),
        )

        assert [session.workspace_label for session in result.unbound] == [""]

    def test_session_carries_workspace_details(self, pos: RepoRoster) -> None:
        session = pos.worktree_sessions[0]

        assert (session.name, session.status, session.workspace_label, session.checkout_path) == (
            "pay-127",
            "working",
            "gchat-dm-task",
            "/work/tt/.worktrees/tt-pos-127",
        )


class TestCoordinator:
    def test_label_matching_repo_name_wins(self, pos: RepoRoster) -> None:
        assert pos.coordinator is not None
        assert pos.coordinator.pane_id == "wX:p1"

    def test_lowest_workspace_number_when_no_label_matches(self) -> None:
        workspaces = workspace_list(
            workspace(workspace_id="wA", label="report", number=9, checkout_path=POS_ROOT),
            workspace(workspace_id="wB", label="other", number=3, checkout_path=POS_ROOT),
        )
        agents = agent_list(
            agent(pane_id="wA:p1", workspace_id="wA"),
            agent(pane_id="wB:p1", workspace_id="wB"),
        )

        result = build_roster(
            workspaces=parse_workspaces(raw=workspaces),
            agents=parse_agents(raw=agents),
        )

        assert result.repos[0].coordinator is not None
        assert result.repos[0].coordinator.pane_id == "wB:p1"

    def test_repo_with_only_worktrees_has_no_coordinator(self, roster: Roster) -> None:
        assert _repo(roster=roster, name="tt-k8s").coordinator is None


class TestRepoFilter:
    def test_filter_keeps_only_that_repo(self) -> None:
        assert [repo.repo_root for repo in _roster(repo_root=K8S_ROOT).repos] == [K8S_ROOT]

    def test_filter_drops_unbound_sessions(self) -> None:
        assert _roster(repo_root=K8S_ROOT).unbound == []


class TestCaller:
    @pytest.mark.parametrize(
        ("cwd", "role", "repo_root", "workspace_id"),
        [
            (POS_ROOT, "main", POS_ROOT, "w1F"),
            (f"{POS_ROOT}/src/payments", "main", POS_ROOT, "w1F"),
            ("/work/tt/.worktrees/tt-pos-127", "worktree", POS_ROOT, "wB8"),
            (f"{POS_ROOT}/.claude/worktrees/agent-a40/src", "worktree", POS_ROOT, "w3Q"),
            ("/home/janusz", "outside", "", ""),
            ("", "outside", "", ""),
        ],
    )
    def test_caller_role_follows_the_closest_checkout(
        self,
        cwd: str,
        role: str,
        repo_root: str,
        workspace_id: str,
    ) -> None:
        caller = _roster(cwd=cwd).caller

        assert (caller.role, caller.repo_root, caller.workspace_id) == (
            role,
            repo_root,
            workspace_id,
        )


class TestToDict:
    def test_roster_serializes_nested_sessions(self, roster: Roster) -> None:
        payload = roster.to_dict()

        assert payload["repos"][1]["coordinator"]["pane_id"] == "wX:p1"
