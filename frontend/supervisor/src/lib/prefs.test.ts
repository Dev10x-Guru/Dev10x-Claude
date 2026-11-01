import { describe, expect, it } from "vitest";

import {
  ASIDE,
  MODAL_HEIGHT,
  MODAL_WIDTH,
  PROJECT_ORDER_KEY,
  PROJECT_PINS_KEY,
  SIDE,
  clampWidth,
  loadAfterAnswer,
  loadApprovedOnly,
  loadHideStopped,
  loadList,
  loadPins,
  loadView,
  loadWidth,
  moveBefore,
  moveBy,
  saveAfterAnswer,
  saveApprovedOnly,
  saveHideStopped,
  saveList,
  savePins,
  saveView,
  saveWidth,
  togglePin,
} from "./prefs";

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

describe("pins", () => {
  it("round-trips", () => {
    const store = memory();
    savePins(["a", "b"], store);
    expect(loadPins(store)).toEqual(["a", "b"]);
  });

  it.each([
    ["not json", []],
    ['{"a":1}', []],
    ['["a", 2, null]', ["a"]],
  ])("reads %j defensively", (raw, expected) => {
    expect(loadPins(memory({ "supervisor.pins": raw }))).toEqual(expected);
  });

  it("toggles", () => {
    expect([togglePin(["a"], "b"), togglePin(["a", "b"], "a")]).toEqual([["a", "b"], ["b"]]);
  });

  it("survives a blocked store", () => {
    savePins(["a"], broken);
    expect([loadPins(broken), loadPins(null)]).toEqual([[], []]);
  });
});

describe("view", () => {
  it.each([
    ["screen", "screen"],
    ["transcript", "transcript"],
    ["garbage", "transcript"],
  ])("reads %s", (raw, expected) => {
    expect(loadView(memory({ "supervisor.view": raw }))).toBe(expected);
  });

  it("saves", () => {
    const store = memory();
    saveView("screen", store);
    expect(store.items.get("supervisor.view")).toBe("screen");
  });
});

describe("after answer", () => {
  it.each([
    ["next", "next"],
    ["stay", "stay"],
    ["garbage", "stay"],
  ])("reads %s", (raw, expected) => {
    expect(loadAfterAnswer(memory({ "supervisor.after-answer": raw }))).toBe(expected);
  });

  it("round-trips and survives a blocked store", () => {
    const store = memory();
    saveAfterAnswer("next", store);
    saveAfterAnswer("next", broken);
    expect([loadAfterAnswer(store), loadAfterAnswer(broken)]).toEqual(["next", "stay"]);
  });
});

describe.each([
  ["session list", ASIDE],
  ["detail panel", SIDE],
  ["project modal width", MODAL_WIDTH],
  ["project modal height", MODAL_HEIGHT],
])("%s size", (_name, panel) => {
  it.each([
    [50, panel.min],
    [9999, panel.max],
    [panel.min + 10.4, panel.min + 10],
  ])("clamps %d", (px, expected) => {
    expect(clampWidth(panel, px)).toBe(expected);
  });

  it("round-trips through the store, clamped", () => {
    const store = memory();
    saveWidth(panel, panel.max + 100, store);
    expect([store.items.has(panel.key), loadWidth(panel, store)]).toEqual([true, panel.max]);
  });

  it.each<Record<string, string>>([{}, { [panel.key]: "wide" }, { [panel.key]: "0" }])(
    "falls back to the default for %j",
    (initial) => {
      expect(loadWidth(panel, memory(initial))).toBe(panel.fallback);
    },
  );

  it("falls back when the store is blocked", () => {
    expect(loadWidth(panel, broken)).toBe(panel.fallback);
  });
});

describe("lists", () => {
  it("round-trips any key", () => {
    const store = memory();
    saveList(PROJECT_ORDER_KEY, ["b", "a"], store);
    expect(loadList(PROJECT_ORDER_KEY, store)).toEqual(["b", "a"]);
  });

  it.each([
    ["c", "a", ["c", "a", "b"]],
    ["a", "c", ["b", "a", "c"]],
    ["a", "a", ["a", "b", "c"]],
    ["new", "b", ["a", "new", "b", "c"]],
    ["a", "gone", ["b", "c", "a"]],
  ])("moves %s before %s", (item, before, expected) => {
    expect(moveBefore(["a", "b", "c"], item, before)).toEqual(expected);
  });

  it.each([
    ["b", -1, ["b", "a", "c"]],
    ["b", 1, ["a", "c", "b"]],
    ["a", -1, ["a", "b", "c"]],
    ["c", 5, ["a", "b", "c"]],
    ["x", 1, ["a", "b", "c"]],
  ])("moves %s by %d", (item, step, expected) => {
    expect(moveBy(["a", "b", "c"], item, step)).toEqual(expected);
  });

  it("keeps project pins and order apart from session pins", () => {
    expect(new Set([PROJECT_PINS_KEY, PROJECT_ORDER_KEY, "supervisor.pins"]).size).toBe(3);
  });
});

describe("hide stopped", () => {
  it.each([true, false])("round-trips %s", (hide) => {
    const store = memory();
    saveHideStopped(hide, store);
    expect(loadHideStopped(store)).toBe(hide);
  });

  it("defaults to showing everything", () => {
    expect([loadHideStopped(memory()), loadHideStopped(broken)]).toEqual([false, false]);
  });
});

describe("approved only", () => {
  it.each([true, false])("round-trips %s", (only) => {
    const store = memory();
    saveApprovedOnly(only, store);
    expect(loadApprovedOnly(store)).toBe(only);
  });

  it("defaults to every call", () => {
    saveApprovedOnly(true, broken);
    expect([loadApprovedOnly(memory()), loadApprovedOnly(broken)]).toEqual([false, false]);
  });
});

it("keeps every remembered size under its own key", () => {
  expect(new Set([ASIDE.key, SIDE.key, MODAL_WIDTH.key, MODAL_HEIGHT.key]).size).toBe(4);
});
