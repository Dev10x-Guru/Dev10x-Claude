import { afterEach, describe, expect, it, vi } from "vitest";

import {
  emptyForm,
  eventBody,
  fetchArtifact,
  isControl,
  isKnownBlock,
  isStale,
  missingRequired,
  toggleOption,
  toneClass,
} from "./artifacts";
import type { ArtifactBlock, ArtifactDocument, FormField } from "./types";

const DOCUMENT: ArtifactDocument = {
  id: "rollout",
  title: "Rollout",
  session: "mc-updates",
  revision: 3,
  updated_at: "2026-11-14T12:00:00+00:00",
  blocks: [{ type: "summary", text: "Ship it." }],
};

const FIELDS: FormField[] = [
  { name: "reason", label: "Reason", required: true },
  { name: "extra", label: "Extra", kind: "textarea" },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("isKnownBlock", () => {
  it.each([
    [{ type: "summary" }, true],
    [{ type: "form" }, true],
    [{ type: "html" }, false],
    [{ type: 3 }, false],
    [{}, false],
  ])("%j → %j", (block, expected) => {
    expect(isKnownBlock(block)).toBe(expected);
  });
});

describe("isControl", () => {
  it.each<[ArtifactBlock, boolean]>([
    [{ id: "a", type: "button", label: "Go" }, true],
    [{ id: "b", type: "choice", prompt: "?", options: ["x"] }, true],
    [{ type: "draft", text: "x" }, false],
  ])("%j → %j", (block, expected) => {
    expect(isControl(block)).toBe(expected);
  });
});

describe("toneClass", () => {
  it.each([
    ["ok", "tone-ok"],
    ["bad", "tone-bad"],
    ["red", ""],
    ['ok" onclick="x', ""],
    [undefined, ""],
  ])("%j → %j", (tone, expected) => {
    expect(toneClass(tone)).toBe(expected);
  });
});

describe("forms", () => {
  it("starts every field empty", () => {
    expect(emptyForm(FIELDS)).toEqual({ reason: "", extra: "" });
  });

  it.each<[Record<string, string>, string[]]>([
    [{ reason: "", extra: "" }, ["Reason"]],
    [{ reason: "  ", extra: "x" }, ["Reason"]],
    [{ reason: "late", extra: "" }, []],
  ])("%j misses %j", (values, expected) => {
    expect(missingRequired(FIELDS, values)).toEqual(expected);
  });
});

describe("toggleOption", () => {
  const options = ["eu", "us", "ap"];

  it.each<[string[], string, string[]]>([
    [[], "us", ["us"]],
    [["ap"], "eu", ["eu", "ap"]],
    [["eu", "us"], "eu", ["us"]],
  ])("%j + %j → %j", (selected, option, expected) => {
    expect(toggleOption(selected, option, options)).toEqual(expected);
  });
});

describe("eventBody", () => {
  it("carries the revision the page shows", () => {
    expect(eventBody(DOCUMENT, "region", "us")).toEqual({
      artifact_id: "rollout",
      control_id: "region",
      value: "us",
      revision: 3,
    });
  });
});

describe("isStale", () => {
  it.each([
    [DOCUMENT, { ...DOCUMENT, revision: 4 }, true],
    [DOCUMENT, { ...DOCUMENT }, false],
    [null, { ...DOCUMENT }, false],
    [DOCUMENT, undefined, false],
  ])("%#", (document, summary, expected) => {
    expect(isStale(document, summary)).toBe(expected);
  });
});

describe("fetchArtifact", () => {
  it("returns the document with the token header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => DOCUMENT });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchArtifact("roll out", "tok");

    expect([result, fetchMock.mock.calls[0][0], fetchMock.mock.calls[0][1].headers["X-Overwatch-Token"]]).toEqual([
      DOCUMENT,
      "/api/artifact?id=roll%20out",
      "tok",
    ]);
  });

  it("returns the server's error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ error: "No such artifact." }) }),
    );

    expect(await fetchArtifact("x", "tok")).toBe("No such artifact.");
  });

  it("falls back to the status code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }));

    expect(await fetchArtifact("x", "tok")).toBe("HTTP 503");
  });

  it("reports a daemon that is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    expect(await fetchArtifact("x", "tok")).toBe("The Overwatch daemon is not answering.");
  });
});
