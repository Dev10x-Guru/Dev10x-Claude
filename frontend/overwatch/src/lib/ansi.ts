export interface Run {
  text: string;
  fg: string;
  bg: string;
  bold: boolean;
  dim: boolean;
  italic: boolean;
  underline: boolean;
}

const BASIC = [
  "#282828", "#cc241d", "#98971a", "#d79921", "#458588", "#b16286", "#689d6a", "#a89984",
  "#928374", "#fb4934", "#b8bb26", "#fabd2f", "#83a598", "#d3869b", "#8ec07c", "#ebdbb2",
];

const SGR = /\x1b\[([0-9;:]*)m/g;
const OTHER_ESCAPES = /\x1b\[[0-9;:?]*[ -/]*[@-ln-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;
const PRIVATE_USE = /[-]|[\u{F0000}-\u{FFFFD}]|[\u{100000}-\u{10FFFD}]/gu;

export function xterm256(index: number): string {
  if (index < 16) return BASIC[index];
  if (index >= 232) {
    const level = 8 + (index - 232) * 10;
    return `rgb(${level}, ${level}, ${level})`;
  }
  const cube = index - 16;
  const scale = (value: number): number => (value === 0 ? 0 : 55 + value * 40);
  return `rgb(${scale(Math.floor(cube / 36))}, ${scale(Math.floor(cube / 6) % 6)}, ${scale(cube % 6)})`;
}

interface Style {
  fg: string;
  bg: string;
  bold: boolean;
  dim: boolean;
  italic: boolean;
  underline: boolean;
}

const PLAIN: Style = { fg: "", bg: "", bold: false, dim: false, italic: false, underline: false };

function extended(codes: number[], at: number): { color: string; used: number } {
  if (codes[at + 1] === 5 && codes[at + 2] !== undefined) {
    return { color: xterm256(codes[at + 2]), used: 2 };
  }
  if (codes[at + 1] === 2 && codes[at + 4] !== undefined) {
    return { color: `rgb(${codes[at + 2]}, ${codes[at + 3]}, ${codes[at + 4]})`, used: 4 };
  }
  return { color: "", used: 0 };
}

function apply(style: Style, params: string): Style {
  const codes = params === "" ? [0] : params.split(/[;:]/).map((part) => Number(part) || 0);
  let next = { ...style };
  for (let at = 0; at < codes.length; at += 1) {
    const code = codes[at];
    if (code === 0) next = { ...PLAIN };
    else if (code === 1) next.bold = true;
    else if (code === 2) next.dim = true;
    else if (code === 3) next.italic = true;
    else if (code === 4) next.underline = true;
    else if (code === 22) next = { ...next, bold: false, dim: false };
    else if (code === 23) next.italic = false;
    else if (code === 24) next.underline = false;
    else if (code >= 30 && code <= 37) next.fg = BASIC[code - 30];
    else if (code >= 90 && code <= 97) next.fg = BASIC[code - 82];
    else if (code === 39) next.fg = "";
    else if (code >= 40 && code <= 47) next.bg = BASIC[code - 40];
    else if (code >= 100 && code <= 107) next.bg = BASIC[code - 92];
    else if (code === 49) next.bg = "";
    else if (code === 38 || code === 48) {
      const { color, used } = extended(codes, at);
      if (code === 38) next.fg = color;
      else next.bg = color;
      at += used;
    }
  }
  return next;
}

export function parseAnsi(input: string): Run[] {
  const source = input.replace(OTHER_ESCAPES, "");
  const runs: Run[] = [];
  let style = { ...PLAIN };
  let last = 0;
  const push = (raw: string): void => {
    const text = raw.replace(PRIVATE_USE, "");
    if (!text) return;
    const previous = runs.at(-1);
    const same =
      previous &&
      previous.fg === style.fg &&
      previous.bg === style.bg &&
      previous.bold === style.bold &&
      previous.dim === style.dim &&
      previous.italic === style.italic &&
      previous.underline === style.underline;
    if (same) previous.text += text;
    else runs.push({ text, ...style });
  };
  for (const match of source.matchAll(SGR)) {
    push(source.slice(last, match.index));
    style = apply(style, match[1]);
    last = match.index + match[0].length;
  }
  push(source.slice(last));
  return runs;
}

export function runLines(input: string): Run[][] {
  return input
    .split("\n")
    .map((line) => parseAnsi(line).filter((run) => run.bg || run.text.trim()))
    .filter((line) => line.length > 0);
}
