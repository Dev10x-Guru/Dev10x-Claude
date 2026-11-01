import { describe, expect, it } from "vitest";

import { countByDay, dayKey, inRange, keyOf, monthGrid, pick } from "./calendar";

describe("monthGrid", () => {
  const october = monthGrid(2026, 9);

  it("starts on the Monday on or before the 1st", () => {
    expect(october[0].slice(0, 4).map((day) => [day.key, day.inMonth])).toEqual([
      ["2026-09-28", false],
      ["2026-09-29", false],
      ["2026-09-30", false],
      ["2026-10-01", true],
    ]);
  });

  it("covers the whole month in full weeks", () => {
    const keys = october.flat().filter((day) => day.inMonth).map((day) => day.day);
    expect([october.length, keys.length, keys.at(-1), october.every((week) => week.length === 7)]).toEqual([
      5,
      31,
      31,
      true,
    ]);
  });

  it("needs six rows for a month that spills over", () => {
    expect(monthGrid(2026, 7).length).toBe(6);
  });
});

describe("pick", () => {
  it.each([
    [{ start: "", end: "" }, "2026-10-05", { start: "2026-10-05", end: "" }],
    [{ start: "2026-10-05", end: "" }, "2026-10-09", { start: "2026-10-05", end: "2026-10-09" }],
    [{ start: "2026-10-05", end: "" }, "2026-10-01", { start: "2026-10-01", end: "2026-10-05" }],
    [{ start: "2026-10-01", end: "2026-10-05" }, "2026-10-20", { start: "2026-10-20", end: "" }],
  ])("from %j picking %s gives %j", (range, key, expected) => {
    expect(pick(range, key)).toEqual(expected);
  });
});

describe("inRange", () => {
  it.each([
    [{ start: "", end: "" }, "2026-10-05", true],
    [{ start: "2026-10-05", end: "" }, "2026-10-05", true],
    [{ start: "2026-10-05", end: "" }, "2026-10-06", false],
    [{ start: "2026-10-01", end: "2026-10-05" }, "2026-10-03", true],
    [{ start: "2026-10-01", end: "2026-10-05" }, "2026-10-06", false],
  ])("%j holds %s: %s", (range, key, expected) => {
    expect(inRange(key, range)).toBe(expected);
  });
});

describe("day keys", () => {
  it("formats local dates and ignores bad input", () => {
    expect([dayKey(new Date(2026, 0, 2)), keyOf("nonsense")]).toEqual(["2026-01-02", ""]);
  });

  it("counts sessions per day", () => {
    const morning = new Date(2026, 9, 30, 9).toISOString();
    const evening = new Date(2026, 9, 30, 20).toISOString();
    const next = new Date(2026, 9, 31, 9).toISOString();
    expect(countByDay([morning, evening, next, "bad"])).toEqual({ "2026-10-30": 2, "2026-10-31": 1 });
  });
});
