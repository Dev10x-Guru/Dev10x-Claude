from __future__ import annotations

import json
from typing import Any

POS_ROOT = "/work/tt/tt-pos"
POS_KEY = f"{POS_ROOT}/.git"
K8S_ROOT = "/work/tt/tt-k8s"
K8S_KEY = f"{K8S_ROOT}/.git"


def workspace(
    *,
    workspace_id: str,
    label: str,
    number: int,
    checkout_path: str | None = None,
    repo_root: str = POS_ROOT,
    repo_name: str = "tt-pos",
    linked: bool = False,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"workspace_id": workspace_id, "label": label, "number": number}
    if checkout_path is not None:
        entry["worktree"] = {
            "checkout_path": checkout_path,
            "is_linked_worktree": linked,
            "repo_key": f"{repo_root}/.git",
            "repo_name": repo_name,
            "repo_root": repo_root,
        }
    return entry


def agent(
    *,
    pane_id: str,
    workspace_id: str,
    status: str = "idle",
    kind: str = "claude",
    cwd: str = POS_ROOT,
    name: str = "",
) -> dict[str, Any]:
    return {
        "agent": kind,
        "agent_status": status,
        "cwd": cwd,
        "pane_id": pane_id,
        "workspace_id": workspace_id,
        "name": name,
        "terminal_title_stripped": f"title {pane_id}",
    }


def workspace_list(*entries: dict[str, Any]) -> str:
    return json.dumps({"result": {"type": "workspace_list", "workspaces": list(entries)}})


def agent_list(*entries: dict[str, Any]) -> str:
    return json.dumps({"result": {"agents": list(entries)}})


WORKSPACES = workspace_list(
    workspace(workspace_id="w1F", label="tt-pos GPV report", number=5, checkout_path=POS_ROOT),
    workspace(workspace_id="wX", label="tt-pos", number=6, checkout_path=POS_ROOT),
    workspace(
        workspace_id="wB8",
        label="gchat-dm-task",
        number=46,
        checkout_path="/work/tt/.worktrees/tt-pos-127",
        linked=True,
    ),
    workspace(
        workspace_id="w3Q",
        label="agent-a40",
        number=20,
        checkout_path=f"{POS_ROOT}/.claude/worktrees/agent-a40",
        linked=True,
    ),
    workspace(
        workspace_id="w5M",
        label="cluster-access",
        number=26,
        checkout_path="/work/tt/.worktrees/tt-k8s-cluster-access",
        repo_root=K8S_ROOT,
        repo_name="tt-k8s",
        linked=True,
    ),
    workspace(workspace_id="w5J", label="workstation", number=15),
)

AGENTS = agent_list(
    agent(pane_id="w1F:p1", workspace_id="w1F", status="idle"),
    agent(pane_id="wX:p1", workspace_id="wX", status="done"),
    agent(pane_id="wB8:p1", workspace_id="wB8", status="working", name="pay-127"),
    agent(pane_id="w3Q:p1", workspace_id="w3Q", status="blocked"),
    agent(pane_id="w5M:p1", workspace_id="w5M", status="idle", cwd=K8S_ROOT),
    agent(pane_id="w5J:p1", workspace_id="w5J", status="done", cwd="/home/janusz"),
    agent(pane_id="wX:p2", workspace_id="wX", kind="codex"),
)
