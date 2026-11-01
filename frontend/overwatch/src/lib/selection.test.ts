import { describe, expect, it } from "vitest";

import { ACK_GRACE_MS, asksQuestion, awaitingAck, nextQuestion, pruneSent, questionKey } from "./selection";
import { makeSession as session } from "./testing";
import type { Decision, Session, ToolCallPreview } from "./types";

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

  it("skips a question already answered until its grace runs out", () => {
    const sessions = [asking("a"), asking("b"), asking("c")];
    const sent = { b: { key: questionKey(sessions[1]), at: 1_000 } };
    expect([
      nextQuestion(sessions, "a", sent, 1_000 + ACK_GRACE_MS - 1),
      nextQuestion(sessions, "a", sent, 1_000 + ACK_GRACE_MS),
    ]).toEqual(["c", "b"]);
  });
});

describe("awaitingAck", () => {
  const prompt = (question: string): Partial<Session> => ({
    status: "waiting",
    preview: question ? { tool: "AskUserQuestion", title: "", kind: "text", body: "", truncated: false } : null,
    prompt: { question, options: [{ key: "1", label: "Yes", detail: "", selected: true }], context: [] },
  });
  const sent = (session: Session) => ({ [session.session_id]: { key: questionKey(session), at: 5 } });

  it("holds while the same question is still on screen", () => {
    const before = session(prompt("Merge?"));
    expect(awaitingAck(before, sent(before))).toEqual({ key: questionKey(before), at: 5 });
  });

  it.each([
    ["the next part of the question", { ...prompt("Release?") }],
    ["the question has gone", { status: "busy" }],
  ])("lets go once %s shows", (_, after) => {
    const before = session(prompt("Merge?"));
    expect(awaitingAck(session(after), sent(before))).toBeNull();
  });

  it("keys a handed-over question by its decisions", () => {
    expect(questionKey(session({ decisions: [decision] }))).toBe("d1");
  });

  it("drops entries the sessions no longer need", () => {
    const still = session({ ...prompt("Merge?"), session_id: "a" });
    const moved = session({ ...prompt("Release?"), session_id: "b" });
    const entries = { a: { key: questionKey(still), at: 1 }, b: { key: "old", at: 1 }, gone: { key: "x", at: 1 } };
    expect(Object.keys(pruneSent([still, moved], entries))).toEqual(["a"]);
  });
});
