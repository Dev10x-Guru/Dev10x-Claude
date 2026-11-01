import { describe, expect, it } from "vitest";

import { parseAnsi, runLines, xterm256 } from "./ansi";

const PLAIN = { fg: "", bg: "", bold: false, dim: false, italic: false, underline: false };

describe("parseAnsi", () => {
  it("reads truecolor powerline segments and drops the separator glyphs", () => {
    const line =
      "\x1b[0m\x1b[38;2;177;98;134m\x1b[0m\x1b[38;2;251;241;199m\x1b[48;2;177;98;134m wt poc " +
      "\x1b[0m\x1b[38;2;177;98;134m\x1b[48;2;215;153;33m\x1b[0m GH-1 \u{F035B} 23%";

    expect(parseAnsi(line)).toEqual([
      { ...PLAIN, text: " wt poc ", fg: "rgb(251, 241, 199)", bg: "rgb(177, 98, 134)" },
      { ...PLAIN, text: " GH-1  23%" },
    ]);
  });

  it.each([
    ["\x1b[31mx", { fg: "#cc241d" }],
    ["\x1b[92mx", { fg: "#b8bb26" }],
    ["\x1b[44mx", { bg: "#458588" }],
    ["\x1b[103mx", { bg: "#fabd2f" }],
    ["\x1b[38;5;208mx", { fg: "rgb(255, 135, 0)" }],
    ["\x1b[48;5;240mx", { bg: "rgb(88, 88, 88)" }],
    ["\x1b[1;2;3;4mx", { bold: true, dim: true, italic: true, underline: true }],
    ["\x1b[1;3;4m\x1b[22;23;24mx", {}],
    ["\x1b[31;41m\x1b[39;49mx", {}],
    ["\x1b[1m\x1b[mx", {}],
    ["\x1b[38;9mx", { fg: "" }],
  ])("styles %j", (input, style) => {
    expect(parseAnsi(input)).toEqual([{ ...PLAIN, text: "x", ...style }]);
  });

  it("ignores non-colour escapes", () => {
    expect(parseAnsi("\x1b[?25l\x1b]8;;https://x\x07link\x1b[2K")).toEqual([{ ...PLAIN, text: "link" }]);
  });

  it("merges neighbours with the same style", () => {
    expect(parseAnsi("a\x1b[0mb")).toEqual([{ ...PLAIN, text: "ab" }]);
  });
});

describe("xterm256", () => {
  it.each([
    [1, "#cc241d"],
    [16, "rgb(0, 0, 0)"],
    [231, "rgb(255, 255, 255)"],
    [232, "rgb(8, 8, 8)"],
  ])("maps %i", (index, color) => {
    expect(xterm256(index)).toBe(color);
  });
});

describe("runLines", () => {
  it("drops blank lines and bare spaces between segments", () => {
    expect(runLines("\x1b[44m a \x1b[0m  \n\n plain ")).toEqual([
      [{ ...PLAIN, text: " a ", bg: "#458588" }],
      [{ ...PLAIN, text: " plain " }],
    ]);
  });
});
