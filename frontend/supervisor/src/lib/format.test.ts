import { describe, expect, it } from "vitest";

import {
  bucket,
  clockTime,
  diffLineKind,
  displayName,
  headline,
  optionText,
  shortPath,
  waitingLabel,
} from "./format";
import { makeSession as session } from "./testing";

describe("bucket", () => {
  it("sorts sessions into their groups", () => {
    const groups = bucket([session({ group: "needs-you" }), session({ group: "working" }), session()]);
    expect([groups["needs-you"].length, groups.working.length, groups.done.length]).toEqual([1, 1, 1]);
  });
});

describe("displayName", () => {
  it.each([
    ["", "kb-84"],
    ["login fix", "login fix"],
  ])("callsign %j shows %j", (callsign, expected) => {
    expect(displayName(session({ callsign }))).toBe(expected);
  });
});

describe("shortPath", () => {
  it.each([
    ["/home/janusz/KB", "~/KB"],
    ["/work/.herdr/worktrees/Dev10x-Claude/perms", "…/Dev10x-Claude/perms"],
    ["/tmp", "/tmp"],
  ])("%s → %s", (path, expected) => {
    expect(shortPath(path)).toBe(expected);
  });
});

describe("optionText", () => {
  it.each([
    ["Relay (Recommended)", "Relay", true],
    ["mc-updates", "mc-updates", false],
  ])("%s", (label, text, recommended) => {
    expect(optionText({ key: "1", label, detail: "", selected: false })).toEqual({ label: text, recommended });
  });
});

describe("waitingLabel", () => {
  it.each([
    [{ waiting_for: "permission prompt" }, "permission prompt"],
    [{ board_state: "needs-input" }, "asked on the bus"],
    [{ status: "busy" }, "busy"],
  ])("%j → %s", (overrides, expected) => {
    expect(waitingLabel(session(overrides))).toBe(expected);
  });
});

describe("headline", () => {
  it.each([
    [0, "Nothing needs you."],
    [1, "One session needs you."],
    [3, "3 sessions need you."],
  ])("%i waiting → %s", (count, expected) => {
    const needs = Array.from({ length: count }, () => session({ group: "needs-you" }));
    expect(headline(bucket(needs))).toBe(expected);
  });
});

describe("diffLineKind", () => {
  it.each([
    ["+++ b/a.py", "file"],
    ["--- a/a.py", "file"],
    ["@@ -1 +1 @@", "hunk"],
    ["+x = 2", "add"],
    ["-x = 1", "del"],
    [" same", "same"],
  ])("%j → %s", (line, kind) => {
    expect(diffLineKind(line)).toBe(kind);
  });
});

describe("clockTime", () => {
  it("returns empty for garbage", () => {
    expect(clockTime("nope")).toBe("");
  });

  it("formats a time", () => {
    expect(clockTime("2026-10-31T12:00:00+00:00")).toMatch(/\d{2}:\d{2}:\d{2}/);
  });
});
