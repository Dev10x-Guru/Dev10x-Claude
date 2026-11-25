import { describe, expect, it } from "vitest";

import { bpmnColors, mermaidConfig, readPalette, toHex } from "./diagram-theme";

describe("toHex", () => {
  it.each([
    ["#ABCDEF", "#abcdef"],
    [" #fff ", "#fff"],
    ["oklch(100% 0 0)", "#ffffff"],
    ["oklch(0% 0 0)", "#000000"],
    ["oklch(0.5 0 0)", "#636363"],
    ["oklch(62.8% 0.2577 29.23)", "#ff0000"],
    ["oklch(97.4% 0.009 85 / 0.5)", "#f9f6f0"],
    ["oklch(50% 0 0deg)", "#636363"],
    ["rgb(0 0 0)", null],
    ["", null],
  ])("%s -> %s", (input, expected) => {
    expect(toHex(input)).toBe(expected);
  });
});

describe("readPalette", () => {
  const tokens: Record<string, string> = {
    "--paper": "oklch(100% 0 0)",
    "--ink": "#000000",
    "--font-body": " Instrument Sans ",
  };
  const read = (token: string) => tokens[token] ?? "";

  it("converts the page's tokens", () => {
    const palette = readPalette(read, false);

    expect([palette.paper, palette.ink, palette.font]).toEqual([
      "#ffffff",
      "#000000",
      "Instrument Sans",
    ]);
  });

  it.each([
    [false, "#f2eee6"],
    [true, "#1b1e24"],
  ])("falls back per scheme when a token is missing (dark=%s)", (dark, expected) => {
    expect(readPalette(read, dark).paperSunk).toBe(expected);
  });

  it("falls back to a generic font", () => {
    expect(readPalette(() => "", false).font).toBe("sans-serif");
  });
});

describe("mermaidConfig", () => {
  const palette = readPalette(() => "", true);
  const config = mermaidConfig(palette, true);

  it("keeps mermaid strict and free of HTML labels", () => {
    expect([config.securityLevel, config.htmlLabels, config.flowchart.htmlLabels]).toEqual([
      "strict",
      false,
      false,
    ]);
  });

  it("themes from the palette", () => {
    expect(config.themeVariables).toMatchObject({
      darkMode: true,
      background: palette.paper,
      primaryTextColor: palette.ink,
      lineColor: palette.inkSoft,
    });
  });
});

describe("bpmnColors", () => {
  it("maps paper and ink onto the renderer defaults", () => {
    const palette = readPalette(() => "", false);

    expect(bpmnColors(palette)).toEqual({
      defaultFillColor: palette.paper,
      defaultStrokeColor: palette.ink,
      defaultLabelColor: palette.ink,
    });
  });
});
