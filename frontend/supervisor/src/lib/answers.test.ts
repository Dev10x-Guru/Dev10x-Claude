import { describe, expect, it } from "vitest";

import {
  ANSWERS_KEPT,
  ANSWERS_KEY,
  changeAnswer,
  correction,
  loadAnswers,
  remember,
  saveAnswers,
  type Answer,
} from "./answers";

function entry(id: string, chosen = "Yes"): Answer {
  return {
    id,
    session_id: `s-${id}`,
    session_name: `name-${id}`,
    question: `Question ${id}?`,
    options: ["Yes", "No"],
    chosen,
    at: "2026-11-01T10:00:00Z",
  };
}

function memory(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  return {
    items,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
  };
}

const broken = {
  getItem: (): string | null => {
    throw new Error("blocked");
  },
  setItem: (): void => {
    throw new Error("full");
  },
};

describe("remember", () => {
  it("puts the newest first and keeps only the last five", () => {
    const list = ["1", "2", "3", "4", "5", "6"].reduce<Answer[]>((all, id) => remember(all, entry(id)), []);
    expect(list.map((answer) => answer.id)).toEqual(["6", "5", "4", "3", "2"]);
    expect(ANSWERS_KEPT).toBe(5);
  });

  it("moves a re-answered question to the top instead of duplicating it", () => {
    const list = remember([entry("2"), entry("1")], entry("1", "No"));
    expect(list.map((answer) => [answer.id, answer.chosen])).toEqual([
      ["1", "No"],
      ["2", "Yes"],
    ]);
  });
});

describe("changeAnswer", () => {
  it("records the new pick and time", () => {
    const [changed] = changeAnswer([entry("1")], "1", "No", "2026-11-01T11:00:00Z");
    expect([changed.chosen, changed.at]).toEqual(["No", "2026-11-01T11:00:00Z"]);
  });

  it("leaves the list alone for an unknown answer", () => {
    const list = [entry("1")];
    expect(changeAnswer(list, "gone", "No", "x")).toBe(list);
  });
});

describe("store", () => {
  it("round-trips", () => {
    const store = memory();
    saveAnswers([entry("1")], store);
    expect(loadAnswers(store)).toEqual([entry("1")]);
  });

  it.each([
    ["not json", []],
    ['{"a":1}', []],
    [JSON.stringify([{ id: "x" }, entry("1"), { ...entry("2"), options: [1] }]), [entry("1")]],
  ])("reads %j defensively", (raw, expected) => {
    expect(loadAnswers(memory({ [ANSWERS_KEY]: raw }))).toEqual(expected);
  });

  it("caps what it reads at five", () => {
    const raw = JSON.stringify(["1", "2", "3", "4", "5", "6"].map((id) => entry(id)));
    expect(loadAnswers(memory({ [ANSWERS_KEY]: raw }))).toHaveLength(5);
  });

  it("survives a blocked store", () => {
    saveAnswers([entry("1")], broken);
    expect([loadAnswers(broken), loadAnswers(null)]).toEqual([[], []]);
  });
});

it("tells the session what changed", () => {
  expect(correction(entry("1"), "No")).toBe(
    [
      'The supervisor changed their answer to an earlier question: "Question 1?".',
      'Earlier answer: "Yes". New answer: "No".',
      "Act on the new answer and undo anything that only made sense under the earlier one.",
    ].join("\n"),
  );
});
