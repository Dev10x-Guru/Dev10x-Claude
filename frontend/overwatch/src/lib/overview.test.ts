import { describe, expect, it } from "vitest";

import { byUrgency, countMarks, isOverviewHash, lastWord, progress, waitingItems } from "./overview";
import { makeSession as session } from "./testing";
import type { Decision, Prompt, SessionRecap, ToolCallPreview } from "./types";

const decision = (id: string, created: string): Decision => ({
  decision_id: id,
  session_id: "s1",
  question: `Question ${id}?`,
  header: `Header ${id}`,
  options: ["A", "B"],
  multi_select: false,
  created,
});

const preview = (tool: string, title = "", body = ""): ToolCallPreview => ({
  tool,
  title,
  kind: "command",
  body,
  truncated: false,
});

const prompt: Prompt = {
  question: "Which hub?",
  options: [
    { key: "1", label: "Relay", detail: "", selected: true },
    { key: "2", label: "mc", detail: "", selected: false },
  ],
  context: [],
};

const recap = (overrides: Partial<SessionRecap> = {}): SessionRecap => ({
  tasks_done: 0,
  tasks_total: 0,
  current_task: "",
  last_said: "",
  last_said_at: "",
  ...overrides,
});

describe("isOverviewHash", () => {
  it.each([
    ["", true],
    ["#", true],
    ["#overview", true],
    ["#sid-1", false],
  ])("%s → %s", (hash, expected) => {
    expect(isOverviewHash(hash)).toBe(expected);
  });
});

describe("waitingItems", () => {
  it("lists recorded decisions oldest first, then what is on screen", () => {
    const sessions = [
      session({ session_id: "late", decisions: [decision("d2", "2026-11-26T09:00:00Z")] }),
      session({ session_id: "early", decisions: [decision("d1", "2026-11-26T08:00:00Z")] }),
      session({
        session_id: "screen",
        status: "waiting",
        waiting_for: "input needed",
        preview: preview("AskUserQuestion"),
        prompt,
      }),
    ];
    expect(waitingItems(sessions).map((item) => [item.key, item.kind])).toEqual([
      ["d1", "decision"],
      ["d2", "decision"],
      ["screen:screen", "question"],
    ]);
  });

  it("describes an on-screen question by its prompt and options", () => {
    const [item] = waitingItems([
      session({ status: "waiting", preview: preview("AskUserQuestion"), prompt }),
    ]);
    expect([item.title, item.detail]).toEqual(["Which hub?", "Relay · mc"]);
  });

  it("names the tool a permission prompt waits on", () => {
    const [item] = waitingItems([
      session({
        status: "waiting",
        waiting_for: "permission prompt",
        preview: preview("Bash", "", "\nrm -rf build\nmore"),
      }),
    ]);
    expect([item.kind, item.title, item.detail]).toEqual(["permission", "Bash: rm -rf build", "rm -rf build"]);
  });

  it("falls back when a permission prompt has no preview", () => {
    const [item] = waitingItems([session({ status: "waiting", waiting_for: "permission prompt" })]);
    expect([item.title, item.detail]).toEqual(["A tool call waits for approval", ""]);
  });

  it("falls back when an on-screen question has no parsed prompt", () => {
    const [item] = waitingItems([session({ status: "waiting", preview: preview("AskUserQuestion") })]);
    expect([item.title, item.detail]).toEqual(["A question is on screen", ""]);
  });

  it("labels any other wait by what the session waits for", () => {
    const [item] = waitingItems([session({ status: "waiting", waiting_for: "input needed" })]);
    expect([item.kind, item.title]).toEqual(["input", "input needed"]);
  });

  it("does not list a waiting session twice when its question is recorded", () => {
    const items = waitingItems([
      session({ status: "waiting", decisions: [decision("d1", "2026-11-26T08:00:00Z")] }),
    ]);
    expect(items.map((item) => item.kind)).toEqual(["decision"]);
  });

  it("names a decision without a header", () => {
    const [item] = waitingItems([session({ decisions: [{ ...decision("d1", ""), header: "" }] })]);
    expect(item.title).toBe("Decision");
  });

  it("skips sessions that are not waiting", () => {
    expect(waitingItems([session({ status: "busy", group: "working" })])).toEqual([]);
  });
});

describe("countMarks", () => {
  it("counts each status mark", () => {
    const sessions = [
      session({ group: "needs-you", status: "waiting" }),
      session({ group: "working", status: "busy" }),
      session({ group: "working", status: "busy" }),
      session({ group: "done", status: "idle" }),
      session({ group: "done", status: "done" }),
    ];
    expect(countMarks(sessions)).toEqual({ blocked: 1, working: 2, done: 1, idle: 1 });
  });
});

describe("byUrgency", () => {
  it("puts blocked sessions first, then working, then by name", () => {
    const sessions = [
      session({ session_id: "idle", name: "a", group: "done", status: "idle" }),
      session({ session_id: "work-b", name: "b", group: "working", status: "busy" }),
      session({ session_id: "work-a", name: "a", group: "working", status: "busy" }),
      session({ session_id: "blocked", name: "z", group: "needs-you", status: "waiting" }),
    ];
    expect(byUrgency(sessions).map((each) => each.session_id)).toEqual(["blocked", "work-a", "work-b", "idle"]);
  });
});

describe("progress", () => {
  it("reports task progress and the current task", () => {
    const tracked = session({ recap: recap({ tasks_done: 2, tasks_total: 5, current_task: "Testing" }) });
    expect(progress(tracked)).toEqual({ done: 2, total: 5, current: "Testing" });
  });

  it.each([
    ["no recap", session()],
    ["no task list", session({ recap: recap() })],
  ])("is empty with %s", (_, each) => {
    expect(progress(each)).toBeNull();
  });
});

describe("lastWord", () => {
  it.each([
    ["the last thing said", session({ recap: recap({ last_said: "Tests pass." }), summary: "s" }), "Tests pass."],
    ["the bus summary", session({ summary: "Waiting on CI" }), "Waiting on CI"],
    ["the bus summary when nothing was said", session({ recap: recap(), summary: "Waiting on CI" }), "Waiting on CI"],
    ["the last screen line", session({ excerpt: "first\n  last line  \n\n" }), "last line"],
    ["nothing", session(), ""],
  ])("falls back to %s", (_, each, expected) => {
    expect(lastWord(each)).toBe(expected);
  });
});
