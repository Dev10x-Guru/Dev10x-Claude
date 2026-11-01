import { describe, expect, it } from "vitest";

import { USAGE_URL, linkify, statusLinks } from "./links";
import { makeWorkspace } from "./testing";

const REPO = "https://github.com/Dev10x-Guru/Dev10x-Claude";
const workspace = makeWorkspace({
  branch: "janusz/GH-1722/bar",
  issue: "GH-1722",
  repo_url: REPO,
  issue_url: `${REPO}/issues/1722`,
  pr: "1730",
  pr_url: `${REPO}/pull/1730`,
});

describe("linkify", () => {
  const links = statusLinks(workspace);

  it("links the PR, the issue, the branch and the usage cells", () => {
    expect(linkify(" janusz/GH-1722/bar  GH-1722  PR#1730  5h 88% ↻3h09m ", links)).toEqual([
      { text: " ", href: "" },
      { text: "janusz/GH-1722/bar", href: `${REPO}/tree/janusz/GH-1722/bar` },
      { text: "  ", href: "" },
      { text: "GH-1722", href: `${REPO}/issues/1722` },
      { text: "  ", href: "" },
      { text: "PR#1730", href: `${REPO}/pull/1730` },
      { text: "  ", href: "" },
      { text: "5h 88% ↻3h09m", href: USAGE_URL },
      { text: " ", href: "" },
    ]);
  });

  it("leaves text without a known token alone", () => {
    expect(linkify(" Opus 5.5 ", links)).toEqual([{ text: " Opus 5.5 ", href: "" }]);
  });

  it("returns nothing for empty text", () => {
    expect(linkify("", links)).toEqual([]);
  });

  it("does not link an issue id that is part of a longer one", () => {
    expect(linkify("GH-17220", links)).toEqual([{ text: "GH-17220", href: "" }]);
  });
});

describe("statusLinks", () => {
  it("offers only the usage link without a repo", () => {
    expect(statusLinks(makeWorkspace({ branch: "main", issue: "PAY-1", pr: "3" })).map((link) => link.href)).toEqual([
      USAGE_URL,
    ]);
  });

  it("encodes each branch path segment", () => {
    const [link] = statusLinks(makeWorkspace({ branch: "a/b#c", repo_url: REPO }));
    expect(link.href).toBe(`${REPO}/tree/a/b%23c`);
  });
});
