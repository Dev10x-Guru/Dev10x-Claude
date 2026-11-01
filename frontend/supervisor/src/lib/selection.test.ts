import { describe, expect, it } from "vitest";

import { asksQuestion, nextQuestion } from "./selection";
import { makeSession as session } from "./testing";
import type { Decision, ToolCallPreview } from "./types";

const question: ToolCallPreview = { tool: "AskUserQuestion", title: "", kind: "text", body: "", truncated: false };

const decision: Decision = {
  decision_id: "d1",
  session_id: "s1",
  question: "Which name?",
  header: "Name",
  options: ["A", "B"],
  multi_select: false,
  created: "2026-11-01T16:00:00+01:00",
};

describe("asksQuestion", () => {
  it.each([
    ["a question on screen", { status: "waiting", preview: question }, true],
    ["a question handed to the page", { status: "waiting", decisions: [decision] }, true],
    ["a permission prompt", { status: "waiting", preview: { ...question, tool: "Bash" } }, false],
    ["a question it has moved past", { status: "busy", preview: question }, false],
  ])("%s → %s", (_, overrides, expected) => {
    expect(asksQuestion(session(overrides))).toBe(expected);
  });
});

describe("nextQuestion", () => {
  const asking = (id: string) => session({ session_id: id, status: "waiting", preview: question });
  const quiet = (id: string) => session({ session_id: id });

  it("picks the next session asking a question, wrapping past the end", () => {
    const sessions = [asking("a"), quiet("b"), asking("c"), asking("d")];
    expect([nextQuestion(sessions, "c"), nextQuestion(sessions, "d")]).toEqual(["d", "a"]);
  });

  it("finds one even when the current session is gone from the list", () => {
    expect(nextQuestion([quiet("b"), asking("c")], "gone")).toBe("c");
  });

  it("returns nothing when no other session asks", () => {
    expect(nextQuestion([asking("a"), quiet("b")], "a")).toBe("");
  });
});
