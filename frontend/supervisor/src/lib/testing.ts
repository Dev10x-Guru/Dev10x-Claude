import type { Session, Workspace } from "./types";

export function makeWorkspace(overrides: Partial<Workspace> = {}): Workspace {
  return {
    project: "KB",
    root: "/home/janusz/KB",
    branch: "",
    issue: "",
    repo_url: "",
    issue_url: "",
    pr: "",
    pr_url: "",
    ...overrides,
  };
}

export function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    session_id: "s1",
    name: "kb-84",
    cwd: "/home/janusz/KB",
    status: "idle",
    waiting_for: "",
    pane_id: "w1:p1",
    callsign: "",
    summary: "",
    board_state: "",
    group: "done",
    prompt: null,
    preview: null,
    excerpt: "",
    status_line: "",
    workspace: makeWorkspace(),
    decisions: [],
    ...overrides,
  };
}
