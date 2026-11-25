export interface DiagramPalette {
  paper: string;
  paperSunk: string;
  ink: string;
  inkSoft: string;
  rule: string;
  ruleStrong: string;
  accent: string;
  accentWash: string;
  font: string;
}

const LIGHT: DiagramPalette = {
  paper: "#faf7f1",
  paperSunk: "#f2eee6",
  ink: "#1e2530",
  inkSoft: "#4f5662",
  rule: "#dcd8d0",
  ruleStrong: "#c1bcb2",
  accent: "#8a5a18",
  accentWash: "#fcefd6",
  font: "sans-serif",
};

const DARK: DiagramPalette = {
  paper: "#13161b",
  paperSunk: "#1b1e24",
  ink: "#eae8e3",
  inkSoft: "#b6b3ac",
  rule: "#2f333a",
  ruleStrong: "#40454d",
  accent: "#e3a64a",
  accentWash: "#3a2f1d",
  font: "sans-serif",
};

const TOKENS: Record<Exclude<keyof DiagramPalette, "font">, string> = {
  paper: "--paper",
  paperSunk: "--paper-sunk",
  ink: "--ink",
  inkSoft: "--ink-soft",
  rule: "--rule",
  ruleStrong: "--rule-strong",
  accent: "--amber-ink",
  accentWash: "--amber-wash",
};

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const OKLCH = /^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*(?:\/[^)]*)?\)$/i;

function gamma(linear: number): number {
  const encoded = linear <= 0.0031308 ? 12.92 * linear : 1.055 * linear ** (1 / 2.4) - 0.055;
  return Math.min(1, Math.max(0, encoded));
}

function channel(value: number): string {
  return Math.round(gamma(value) * 255)
    .toString(16)
    .padStart(2, "0");
}

export function toHex(color: string): string | null {
  const value = color.trim();
  if (HEX.test(value)) return value.toLowerCase();
  const match = OKLCH.exec(value);
  if (!match) return null;
  const lightness = Number(match[1]) / (match[2] ? 100 : 1);
  const chroma = Number(match[3]);
  const hue = (Number(match[4]) * Math.PI) / 180;
  const a = chroma * Math.cos(hue);
  const b = chroma * Math.sin(hue);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const red = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const green = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const blue = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return `#${channel(red)}${channel(green)}${channel(blue)}`;
}

export function readPalette(read: (token: string) => string, dark: boolean): DiagramPalette {
  const fallback = dark ? DARK : LIGHT;
  const palette = { ...fallback };
  for (const [key, token] of Object.entries(TOKENS) as [keyof typeof TOKENS, string][]) {
    palette[key] = toHex(read(token)) ?? fallback[key];
  }
  palette.font = read("--font-body").trim() || fallback.font;
  return palette;
}

export function pagePalette(dark: boolean): DiagramPalette {
  const style = getComputedStyle(document.documentElement);
  return readPalette((token) => style.getPropertyValue(token), dark);
}

export function mermaidConfig(palette: DiagramPalette, dark: boolean) {
  return {
    startOnLoad: false,
    securityLevel: "strict" as const,
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    theme: "base" as const,
    darkMode: dark,
    fontFamily: palette.font,
    themeVariables: {
      darkMode: dark,
      fontFamily: palette.font,
      background: palette.paper,
      mainBkg: palette.paperSunk,
      primaryColor: palette.paperSunk,
      primaryTextColor: palette.ink,
      primaryBorderColor: palette.ruleStrong,
      secondaryColor: palette.accentWash,
      secondaryTextColor: palette.ink,
      secondaryBorderColor: palette.accent,
      tertiaryColor: palette.paper,
      tertiaryTextColor: palette.ink,
      tertiaryBorderColor: palette.rule,
      lineColor: palette.inkSoft,
      textColor: palette.ink,
      noteBkgColor: palette.accentWash,
      noteTextColor: palette.ink,
      noteBorderColor: palette.accent,
    },
  };
}

export interface BpmnColors {
  defaultFillColor: string;
  defaultStrokeColor: string;
  defaultLabelColor: string;
}

export function bpmnColors(palette: DiagramPalette): BpmnColors {
  return {
    defaultFillColor: palette.paper,
    defaultStrokeColor: palette.ink,
    defaultLabelColor: palette.ink,
  };
}
