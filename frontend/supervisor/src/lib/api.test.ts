import { afterEach, describe, expect, it, vi } from "vitest";

import { post, readToken } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readToken", () => {
  it.each([
    ["?token=abc", "abc"],
    ["", ""],
  ])("%j → %j", (search, expected) => {
    expect(readToken(search)).toBe(expected);
  });
});

describe("post", () => {
  it("sends JSON with the token header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, sent: "1" }) });
    vi.stubGlobal("fetch", fetchMock);

    const result = await post("/keys", { key: "1" }, "tok");

    expect([result, fetchMock.mock.calls[0][1].headers["X-Supervisor-Token"]]).toEqual([
      { ok: true, sent: "1" },
      "tok",
    ]);
  });

  it("returns the server's error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ error: "Already answered." }) }),
    );

    expect(await post("/answer", {}, "tok")).toEqual({ ok: false, error: "Already answered." });
  });

  it("falls back to the status code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));

    expect(await post("/answer", {}, "tok")).toEqual({ ok: false, error: "HTTP 500" });
  });

  it("reports a daemon that is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    expect(await post("/answer", {}, "tok")).toEqual({
      ok: false,
      error: "The supervisor daemon is not answering.",
    });
  });
});
