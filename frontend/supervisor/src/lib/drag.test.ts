import { describe, expect, it } from "vitest";

import { PROJECT_MIME, SESSION_MIME, carriesProject, carriesSession, droppedPeer } from "./drag";

describe("carriesSession", () => {
  it.each([
    [[SESSION_MIME, "text/plain"], true],
    [["text/plain"], false],
    [undefined, false],
  ])("reads %j", (types, expected) => {
    expect(carriesSession(types)).toBe(expected);
  });
});

describe("carriesProject", () => {
  it.each([
    [[PROJECT_MIME], true],
    [[SESSION_MIME], false],
    [undefined, false],
  ])("reads %j", (types, expected) => {
    expect(carriesProject(types)).toBe(expected);
  });
});

describe("droppedPeer", () => {
  it.each([
    [" sid-b ", "sid-a", "sid-b"],
    ["sid-a", "sid-a", ""],
    ["", "sid-a", ""],
  ])("takes %j onto %s", (data, current, expected) => {
    expect(droppedPeer(data, current)).toBe(expected);
  });
});
