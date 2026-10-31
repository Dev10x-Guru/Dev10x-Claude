import { describe, expect, it } from "vitest";

import {
  ASIDE_DEFAULT_PX,
  ASIDE_MAX_PX,
  ASIDE_MIN_PX,
  clampAside,
  loadAsideWidth,
  loadPins,
  loadView,
  saveAsideWidth,
  savePins,
  saveView,
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

describe("aside width", () => {
  it.each([
    [50, ASIDE_MIN_PX],
    [9999, ASIDE_MAX_PX],
    [300.4, 300],
  ])("clamps %d", (px, expected) => {
    expect(clampAside(px)).toBe(expected);
  });

  it("round-trips through the store, clamped", () => {
    const store = memory();
    saveAsideWidth(1200, store);
    expect(loadAsideWidth(store)).toBe(ASIDE_MAX_PX);
  });

  it.each<Record<string, string>>([{}, { "supervisor.aside-width": "wide" }, { "supervisor.aside-width": "0" }])(
    "falls back to the default for %j",
    (initial) => {
      expect(loadAsideWidth(memory(initial))).toBe(ASIDE_DEFAULT_PX);
    },
  );

  it("falls back when the store is blocked", () => {
    expect(loadAsideWidth(broken)).toBe(ASIDE_DEFAULT_PX);
  });
});
