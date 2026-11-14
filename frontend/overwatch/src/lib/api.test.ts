import { afterEach, describe, expect, it, vi } from "vitest";

import { checkToken, forgetToken, post, readToken, resolveToken } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const items = new Map(Object.entries(initial));
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => void items.delete(key),
    setItem: (key: string, value: string) => void items.set(key, value),
  };
}

function brokenStorage(): Storage {
  const fail = (): never => {
    throw new Error("blocked");
  };
  return { length: 0, clear: fail, getItem: fail, key: fail, removeItem: fail, setItem: fail };
}

describe("resolveToken", () => {
  it("remembers a token given in the link", () => {
    const storage = memoryStorage();

    const found = resolveToken("?token=fresh", storage);

    expect([found, storage.getItem("overwatch.token")]).toEqual([{ token: "fresh", remembered: false }, "fresh"]);
  });

  it("falls back to the remembered token", () => {
    expect(resolveToken("", memoryStorage({ "overwatch.token": "old" }))).toEqual({
      token: "old",
      remembered: true,
    });
  });

  it.each([
    ["no storage", null, "?token=a", { token: "a", remembered: false }],
    ["nothing remembered", memoryStorage(), "", { token: "", remembered: true }],
    ["blocked storage, link token", brokenStorage(), "?token=a", { token: "a", remembered: false }],
    ["blocked storage, no link token", brokenStorage(), "", { token: "", remembered: false }],
  ])("%s", (_name, storage, search, expected) => {
    expect(resolveToken(search, storage)).toEqual(expected);
  });
});

describe("forgetToken", () => {
  it("drops the remembered token", () => {
    const storage = memoryStorage({ "overwatch.token": "old" });

    forgetToken(storage);

    expect(storage.getItem("overwatch.token")).toBeNull();
  });

  it("tolerates blocked storage", () => {
    expect(() => forgetToken(brokenStorage())).not.toThrow();
  });
});

describe("checkToken", () => {
  it.each([
    [403, "rejected"],
    [200, "ok"],
  ])("HTTP %i → %s", async (status, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status }));

    expect(await checkToken("tok")).toBe(expected);
  });

  it("reports a daemon that is down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    expect(await checkToken("tok")).toBe("down");
  });
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

    expect([result, fetchMock.mock.calls[0][1].headers["X-Overwatch-Token"]]).toEqual([
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
      error: "The Overwatch daemon is not answering.",
    });
  });
});
