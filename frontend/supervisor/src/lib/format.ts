import type { Group, PromptOption, Session } from "./types";

const RECOMMENDED = /\s*\(recommended\)\s*$/i;

export function bucket(sessions: Session[]): Record<Group, Session[]> {
  const groups: Record<Group, Session[]> = { "needs-you": [], working: [], done: [] };
  for (const session of sessions) groups[session.group].push(session);
  return groups;
}

export function displayName(session: Session): string {
  if (session.callsign) return session.callsign;
  const issue = session.workspace?.issue;
  const prefix = issue ? `${issue}-` : "";
  return prefix && session.name.startsWith(prefix) && session.name.length > prefix.length
    ? session.name.slice(prefix.length)
    : session.name;
}

export function shortPath(path: string, home = "/home/janusz"): string {
  const withHome = path.startsWith(home) ? `~${path.slice(home.length)}` : path;
  const parts = withHome.split("/").filter(Boolean);
  return parts.length > 3 ? `…/${parts.slice(-2).join("/")}` : withHome;
}

export function optionText(option: PromptOption): { label: string; recommended: boolean } {
  return {
    label: option.label.replace(RECOMMENDED, ""),
    recommended: RECOMMENDED.test(option.label),
  };
}

export function waitingLabel(session: Session): string {
  if (session.waiting_for) return session.waiting_for;
  if (session.board_state === "needs-input") return "asked on the bus";
  return session.status;
}

export function headline(groups: Record<Group, Session[]>): string {
  const waiting = groups["needs-you"].length;
  if (waiting === 0) return "Nothing needs you.";
  return waiting === 1 ? "One session needs you." : `${waiting} sessions need you.`;
}

export type DiffLineKind = "add" | "del" | "hunk" | "file" | "same";

export function diffLineKind(line: string): DiffLineKind {
  if (line.startsWith("+++") || line.startsWith("---")) return "file";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "same";
}

export function clockTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
