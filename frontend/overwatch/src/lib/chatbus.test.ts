import { afterEach, describe, expect, it, vi } from "vitest";

import { busTime, byStatus, fetchBoard, isBusRoute, member, threadUrl, type BusWorkItem } from "./chatbus";

function item(id: number, status: BusWorkItem["status"]): BusWorkItem {
  return {
    id,
    kind: "reply",
    status,
    claimed_by: null,
    claimed_until: null,
    attempts: 0,
    result: null,
    event_type: "google.workspace.chat.message.v1.created",
    space: "spaces/AAAA",
    sender: "users/2",
    thread: null,
    untrusted_text: "hi",
    created_at: "2026-11-06T12:00:00.000000Z",
  };
}

describe("isBusRoute", () => {
  it.each([
    ["#/bus", true],
    ["#/bus/", true],
    ["#/a/bus", false],
    ["#bus", false],
  ])("reads %s as %s", (hash, expected) => {
    expect(isBusRoute(hash)).toBe(expected);
  });
});

describe("threadUrl", () => {
  it("links a well-formed thread name", () => {
    expect(threadUrl("spaces/AAAA/threads/t-1_x")).toBe("https://chat.google.com/room/AAAA/t-1_x");
  });

  it.each([
    [null],
    [""],
    ["javascript:alert(1)"],
    ["spaces/AAAA/threads/t1/../../evil"],
    ['spaces/AAAA/threads/"><script>'],
  ])("refuses to link %s", (thread) => {
    expect(threadUrl(thread)).toBe("");
  });
});

describe("member", () => {
  it.each([
    [null, "none"],
    [{ chat_user: "users/1", login: "janusz" }, "janusz (users/1)"],
    [{ chat_user: "users/1", login: null }, "users/1"],
  ])("describes %j as %s", (entry, expected) => {
    expect(member(entry)).toBe(expected);
  });
});

describe("busTime", () => {
  it.each([
    ["2026-11-06T12:00:00.000000Z", "2026-11-06 12:00:00 UTC"],
    ["2026-11-06T12:00:00Z", "2026-11-06 12:00:00 UTC"],
    ["yesterday", "yesterday"],
  ])("formats %s", (value, expected) => {
    expect(busTime(value)).toBe(expected);
  });
});

describe("byStatus", () => {
  it("groups items with approvals first and drops empty groups", () => {
    const groups = byStatus([item(1, "done"), item(2, "awaiting_approval"), item(3, "done")]);
    expect(groups.map((group) => [group.status, group.items.map((each) => each.id)])).toEqual([
      ["awaiting_approval", [2]],
      ["done", [1, 3]],
    ]);
  });
});

describe("fetchBoard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the board on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ exists: false }), { status: 200 })));
    expect(await fetchBoard("tok")).toEqual({ exists: false });
  });

  it("returns the server's error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "disk" }), { status: 503 })));
    expect(await fetchBoard("tok")).toBe("disk");
  });

  it("falls back to the HTTP status", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({}), { status: 502 })));
    expect(await fetchBoard("tok")).toBe("HTTP 502");
  });

  it("reports a daemon that is down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("down");
      }),
    );
    expect(await fetchBoard("tok")).toBe("The Overwatch daemon is not answering.");
  });
});
