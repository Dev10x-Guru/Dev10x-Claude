import { describe, expect, it } from "vitest";

import { parseRoute, routeHash, type Route } from "./route";

describe("parseRoute", () => {
  it.each<[string, Route]>([
    ["", { kind: "session", sessionId: "" }],
    ["#sid-1", { kind: "session", sessionId: "sid-1" }],
    ["#artifact/rollout", { kind: "artifact", artifactId: "rollout" }],
    ["#artifact/a%20b", { kind: "artifact", artifactId: "a b" }],
    ["#artifact/%E0%A4%A", { kind: "artifact", artifactId: "" }],
    ["#%E0%A4%A", { kind: "session", sessionId: "" }],
  ])("%j", (hash, expected) => {
    expect(parseRoute(hash)).toEqual(expected);
  });
});

describe("routeHash", () => {
  it.each<[Route, string]>([
    [{ kind: "session", sessionId: "sid 1" }, "#sid%201"],
    [{ kind: "artifact", artifactId: "rollout" }, "#artifact/rollout"],
  ])("%j → %j", (route, expected) => {
    expect(routeHash(route)).toBe(expected);
  });

  it("round-trips", () => {
    const route: Route = { kind: "artifact", artifactId: "rollout-review" };

    expect(parseRoute(routeHash(route))).toEqual(route);
  });
});
