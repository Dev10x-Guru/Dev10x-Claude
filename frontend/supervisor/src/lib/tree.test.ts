import { describe, expect, it } from "vitest";

import { pickSession } from "./selection";
import { makeSession, makeWorkspace } from "./testing";
import { buildTree, markOf, matches } from "./tree";

const DX = "/work/dx/Dev10x-Claude";
const WT = "/work/.herdr/worktrees/Dev10x-Claude/poc";

function at(id: string, project: string, root: string, group: "needs-you" | "working" | "done" = "done") {
  return makeSession({
    session_id: id,
    name: id,
    cwd: root,
    group,
    status: group === "done" ? "idle" : group === "working" ? "busy" : "waiting",
    workspace: makeWorkspace({ project, root }),
  });
}

describe("markOf", () => {
  it.each([
    [{ group: "needs-you" as const }, "blocked"],
    [{ group: "working" as const }, "working"],
    [{ group: "done" as const, status: "idle" }, "idle"],
    [{ group: "done" as const, status: "" }, "done"],
  ])("maps %o to %s", (overrides, mark) => {
    expect(markOf(makeSession(overrides))).toBe(mark);
  });
});

describe("buildTree", () => {
  const tree = buildTree([
    at("zeta", "Dev10x-Claude", DX),
    at("alpha", "Dev10x-Claude", WT, "working"),
    at("beta", "Dev10x-Claude", WT),
    at("kb", "KB", "/kb", "needs-you"),
  ]);

  it("puts the project that needs you first", () => {
    expect(tree.map((project) => [project.name, project.mark, project.count])).toEqual([
      ["KB", "blocked", 1],
      ["Dev10x-Claude", "working", 3],
    ]);
  });

  it("folds worktrees under their project, busiest folder first", () => {
    expect(tree[1].folders.map((folder) => [folder.root, folder.sessions.map((s) => s.name)])).toEqual([
      [WT, ["alpha", "beta"]],
      [DX, ["zeta"]],
    ]);
  });

  it("falls back to the folder when the workspace is unknown", () => {
    const [project] = buildTree([makeSession({ cwd: "/x", workspace: makeWorkspace({ project: "", root: "" }) })]);
    expect([project.name, project.folders[0].root]).toEqual(["/x", "/x"]);
  });
});

describe("matches", () => {
  const session = makeSession({
    name: "mc-updates",
    workspace: makeWorkspace({ branch: "janusz/GH-1722/bar", issue: "GH-1722" }),
  });

  it.each([
    ["", true],
    ["  ", true],
    ["MC-UP", true],
    ["gh-1722", true],
    ["nope", false],
  ])("matches %j: %s", (query, expected) => {
    expect(matches(session, query)).toBe(expected);
  });
});

describe("pickSession", () => {
  const idle = at("idle", "p", "/p");
  const busy = at("busy", "p", "/p", "working");
  const asking = at("asking", "p", "/p", "needs-you");

  it.each([
    [[idle, busy, asking], "idle", "idle"],
    [[idle, busy, asking], "gone", "asking"],
    [[idle, busy], "", "busy"],
    [[idle], "", "idle"],
  ])("picks from %#", (sessions, chosen, expected) => {
    expect(pickSession(sessions, chosen)?.session_id).toBe(expected);
  });

  it("returns null with no sessions", () => {
    expect(pickSession([], "x")).toBeNull();
  });
});
