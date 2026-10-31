export interface Dialog {
  title: string;
  description: string[];
  body: string;
  notes: string[];
}

const DASHED = /^\s*[╌┄-]{8,}\s*$/;
const GUTTER = /^\s*│\s?/;
const TAB_MARKS = /^[☐☑☒✓✔]\s*/u;

export function splitDialog(context: string[]): Dialog | null {
  const lines = context.map((line) => line.replace(/\s+$/, ""));
  if (!lines.some((line) => line.trim())) return null;
  const rules = lines.flatMap((line, index) => (DASHED.test(line) ? [index] : []));
  const headEnd = rules.length >= 2 ? rules[0] : lines.length;
  const head = lines
    .slice(0, headEnd)
    .map((line) => line.replace(GUTTER, "").trim())
    .filter(Boolean);
  const body =
    rules.length >= 2
      ? lines
          .slice(rules[0] + 1, rules[rules.length - 1])
          .filter((line) => !DASHED.test(line))
          .map((line) => line.replace(GUTTER, "").trimStart())
          .join("\n")
      : "";
  const notes =
    rules.length >= 2
      ? lines
          .slice(rules[rules.length - 1] + 1)
          .map((line) => line.trim())
          .filter(Boolean)
      : [];
  return { title: (head[0] ?? "").replace(TAB_MARKS, ""), description: head.slice(1), body, notes };
}
