import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cellText,
  controlState,
  deliveryReport,
  describeValue,
  fetchArtifact,
  findControl,
  formatRoute,
  isPending,
  navGroups,
  parseRoute,
  pickView,
  sendControl,
  sentKey,
  share,
  standaloneBlocks,
  type ArtifactDocument,
  type ArtifactView,
} from "./artifact";

afterEach(() => {
  vi.unstubAllGlobals();
});

function makeView(overrides: Partial<ArtifactView> = {}): ArtifactView {
  return { id: "summary", label: "Summary", blocks: [], ...overrides };
}

function makeDocument(overrides: Partial<ArtifactDocument> = {}): ArtifactDocument {
  return {
    schema: "dev10x.artifact/v1",
    id: "rollout-review",
    title: "Rollout review",
    revision: 3,
    updated_at: "2026-11-14T10:00:00+01:00",
    owner: { session_id: "s1", name: "kb-84" },
    views: [
      makeView(),
      makeView({
        id: "act",
        label: "Act",
        blocks: [
          { type: "button", id: "ship", label: "Ship it" },
          { type: "choice", id: "pick", label: "Pick", options: ["a", "b"] },
        ],
      }),
    ],
    events: [],
    ...overrides,
  };
}

describe("parseRoute", () => {
  it.each([
    ["#/a/rollout-review", { id: "rollout-review", view: "" }],
    ["#/a/rollout-review/", { id: "rollout-review", view: "" }],
    ["#/a/rollout-review/act", { id: "rollout-review", view: "act" }],
    ["#/a/a%20b/c%2Fd", { id: "a b", view: "c/d" }],
    ["#s1", null],
    ["", null],
    ["#/a/", null],
    ["#/a/x/y/z", null],
    ["#/a/%E0%A4%A", null],
  ])("%j → %j", (hash, expected) => {
    expect(parseRoute(hash)).toEqual(expected);
  });
});

describe("formatRoute", () => {
  it.each([
    ["rollout-review", "", "#/a/rollout-review"],
    ["rollout-review", "act", "#/a/rollout-review/act"],
    ["a b", "c/d", "#/a/a%20b/c%2Fd"],
  ])("%j %j → %j", (id, view, expected) => {
    expect(formatRoute(id, view)).toBe(expected);
  });

  it("round-trips through parseRoute", () => {
    expect(parseRoute(formatRoute("x-1", "v-2"))).toEqual({ id: "x-1", view: "v-2" });
  });
});

describe("pickView", () => {
  it.each([
    ["act", "act"],
    ["missing", "summary"],
    ["", "summary"],
  ])("%j → %j", (requested, expected) => {
    expect(pickView(makeDocument(), requested).id).toBe(expected);
  });
});

describe("navGroups", () => {
  it("keeps first-seen group order and view order", () => {
    const views = [
      makeView({ id: "a", group: "Overview" }),
      makeView({ id: "b", group: "Detail" }),
      makeView({ id: "c", group: "Overview" }),
      makeView({ id: "d" }),
    ];

    expect(navGroups(views).map((group) => [group.group, group.views.map((view) => view.id)])).toEqual([
      ["Overview", ["a", "c"]],
      ["Detail", ["b"]],
      ["", ["d"]],
    ]);
  });
});

describe("findControl", () => {
  it.each([
    ["ship", "button"],
    ["pick", "choice"],
    ["nope", null],
  ])("%j → %j", (id, expected) => {
    expect(findControl(makeDocument(), id)?.type ?? null).toBe(expected);
  });
});

describe("standaloneBlocks", () => {
  it("leaves out a control its decision already shows", () => {
    const view = makeView({
      blocks: [
        { type: "decisions", items: [{ question: "Ship?", control: "ship" }, { question: "Later?" }] },
        { type: "button", id: "ship", label: "Ship it" },
        { type: "choice", id: "pick", label: "Pick", options: ["a", "b"] },
      ],
    });

    expect(standaloneBlocks(view).map((block) => block.type)).toEqual(["decisions", "choice"]);
  });
});

describe("deliveryReport", () => {
  it.each([
    [{ ok: true, recorded: true }, "Sent x"],
    [{ ok: true }, "Sent x"],
    [{ ok: true, recorded: false }, "Sent x, but the page could not record it; do not send it again"],
  ])("%j → %j", (result, expected) => {
    expect(deliveryReport(result, "Sent x")).toBe(expected);
  });
});

describe("isPending", () => {
  it.each([
    ["sent locally at the current revision", { [sentKey("rollout-review", "ship")]: 3 }, [], true],
    ["sent locally at an older revision", { [sentKey("rollout-review", "ship")]: 2 }, [], false],
    ["recorded by the server at the current revision", {}, [{ kind: "control", control_id: "ship", revision: 3 }], true],
    ["recorded by the server at an older revision", {}, [{ kind: "control", control_id: "ship", revision: 2 }], false],
    ["recorded for another control", {}, [{ kind: "control", control_id: "pick", revision: 3 }], false],
    ["a share at the current revision", {}, [{ kind: "share", publisher: "claude-ai", revision: 3 }], false],
    ["never sent", {}, [], false],
  ])("%s → %j", (_label, sent, events, expected) => {
    expect(isPending(makeDocument({ events }), "ship", sent)).toBe(expected);
  });
});

describe("controlState", () => {
  it.each([
    [{ live: true, pending: false, sending: true, error: "" }, "sending"],
    [{ live: false, pending: true, sending: false, error: "" }, "pending"],
    [{ live: false, pending: false, sending: false, error: "boom" }, "offline"],
    [{ live: true, pending: false, sending: false, error: "boom" }, "error"],
    [{ live: true, pending: false, sending: false, error: "" }, "ready"],
  ])("%j → %j", (facts, expected) => {
    expect(controlState(facts)).toBe(expected);
  });
});

describe("describeValue", () => {
  it.each([
    ["yes", "yes"],
    [["a", "b"], "a, b"],
    [{ reason: "late", owner: "me" }, "reason: late; owner: me"],
    [undefined, ""],
    [3, "3"],
  ])("%j → %j", (value, expected) => {
    expect(describeValue(value)).toBe(expected);
  });
});

describe("cellText", () => {
  it.each([
    ["plain", { text: "plain" }],
    [{ text: "red", tone: "bad" as const }, { text: "red", tone: "bad" }],
  ])("%j → %j", (cell, expected) => {
    expect(cellText(cell)).toEqual(expected);
  });
});

describe("fetchArtifact", () => {
  it("asks for the document with the token header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => makeDocument() });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchArtifact("a b", "tok");

    expect([
      (result as ArtifactDocument).id,
      fetchMock.mock.calls[0][0],
      fetchMock.mock.calls[0][1].headers["X-Overwatch-Token"],
    ]).toEqual(["rollout-review", "/api/artifact?id=a%20b", "tok"]);
  });

  it("returns the server's error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ error: "No such artifact." }) }),
    );

    expect(await fetchArtifact("x", "tok")).toBe("No such artifact.");
  });

  it("falls back to the status code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));

    expect(await fetchArtifact("x", "tok")).toBe("HTTP 500");
  });

  it("reports a daemon that is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    expect(await fetchArtifact("x", "tok")).toBe("The Overwatch daemon is not answering.");
  });
});

describe("sendControl", () => {
  it("posts the event body to /artifact/event", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, channel: "prompt", event_id: "e1" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendControl(
      { artifact_id: "rollout-review", revision: 3, control_id: "pick", value: ["a", "b"] },
      "tok",
    );

    expect([result.ok, fetchMock.mock.calls[0][0], JSON.parse(fetchMock.mock.calls[0][1].body)]).toEqual([
      true,
      "/artifact/event",
      { artifact_id: "rollout-review", revision: 3, control_id: "pick", value: ["a", "b"] },
    ]);
  });

  it("surfaces a stale-page conflict", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({ error: "The page changed; reload it." }),
      }),
    );

    expect(
      await sendControl({ artifact_id: "x", revision: 1, control_id: "ship", value: "Ship it" }, "tok"),
    ).toEqual({ ok: false, error: "The page changed; reload it." });
  });
});

describe("share", () => {
  it("posts the publisher to /artifact/share", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, channel: "relay" }) });
    vi.stubGlobal("fetch", fetchMock);

    await share("rollout-review", "claude-ai", "tok");

    expect([fetchMock.mock.calls[0][0], JSON.parse(fetchMock.mock.calls[0][1].body)]).toEqual([
      "/artifact/share",
      { artifact_id: "rollout-review", publisher: "claude-ai" },
    ]);
  });
});
