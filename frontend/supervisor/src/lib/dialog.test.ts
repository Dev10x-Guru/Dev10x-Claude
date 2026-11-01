import { describe, expect, it } from "vitest";

import { parseSteps, splitDialog } from "./dialog";

const DASH = "╌".repeat(40);

describe("splitDialog", () => {
  it("splits a Bash permission dialog into title, command and the rule that asked", () => {
    expect(
      splitDialog([
        " Bash command",
        " Rerun the integration suite inside the rebuilt image",
        DASH,
        " │ docker run --rm --network host -v /src:/src:ro",
        "   --entrypoint bash tt-airflow:check /run-in-image.sh   ",
        DASH,
        " Permission rule Bash(docker run:*) requires confirmation for this command.",
        " /permissions to update rules",
      ]),
    ).toEqual({
      title: "Bash command",
      description: ["Rerun the integration suite inside the rebuilt image"],
      body: "docker run --rm --network host -v /src:/src:ro\n--entrypoint bash tt-airflow:check /run-in-image.sh",
      notes: ["Permission rule Bash(docker run:*) requires confirmation for this command.", "/permissions to update rules"],
    });
  });

  it("keeps a dialog without a command block as title and description", () => {
    expect(splitDialog([" Edit file", " src/app.py", "", " Make this edit?"])).toEqual({
      title: "Edit file",
      description: ["src/app.py", "Make this edit?"],
      body: "",
      notes: [],
    });
  });

  it.each([" ☐ Push/PR", " ☒ Push/PR", " ✔ Push/PR"])("drops the widget's tab mark from %j", (line) => {
    expect(splitDialog([line])?.title).toBe("Push/PR");
  });

  it("drops the question widget's gutter from the header", () => {
    expect(splitDialog([" ☐ Review", "", "│ PR #507 is green."])?.description).toEqual(["PR #507 is green."]);
  });

  it("returns nothing for an empty block", () => {
    expect([splitDialog([]), splitDialog(["  ", ""])]).toEqual([null, null]);
  });
});

describe("parseSteps", () => {
  it("reads the question widget's tab bar, marking the first open tab as current", () => {
    expect(parseSteps("←  ☒ F5a  ☐ F5c env  ☐ F6 ~/.claude  ✔ Submit  →")).toEqual([
      { label: "F5a", done: true, current: false },
      { label: "F5c env", done: false, current: true },
      { label: "F6 ~/.claude", done: false, current: false },
      { label: "Submit", done: true, current: false },
    ]);
  });

  it.each(["Bash command", "← back to the list", ""])("finds no tab bar in %j", (title) => {
    expect(parseSteps(title)).toEqual([]);
  });
});
