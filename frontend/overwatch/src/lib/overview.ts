import { displayName, waitingLabel } from "./format";
import { markOf, type Mark } from "./tree";
import type { Session } from "./types";

export const OVERVIEW_HASH = "#overview";

const QUESTION_TOOL = "AskUserQuestion";
const PERMISSION = "permission prompt";
const RANK: Record<Mark, number> = { blocked: 0, working: 1, done: 2, idle: 3 };

export type WaitKind = "decision" | "question" | "permission" | "input";

export interface Waiting {
  key: string;
  session: Session;
  kind: WaitKind;
  title: string;
  detail: string;
  since: string;
}

export interface Progress {
  done: number;
  total: number;
  current: string;
}

export function isOverviewHash(hash: string): boolean {
  return hash === "" || hash === "#" || hash === OVERVIEW_HASH;
}

function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim())?.trim() ?? "";
}

function onScreen(session: Session): Waiting | null {
  if (session.status !== "waiting" || session.decisions.length) return null;
  const base = { key: `screen:${session.session_id}`, session, since: "" };
  const prompt = session.prompt;
  const preview = session.preview;
  if (preview?.tool === QUESTION_TOOL) {
    return {
      ...base,
      kind: "question",
      title: prompt?.question || "A question is on screen",
      detail: prompt?.options.map((option) => option.label).join(" · ") ?? "",
    };
  }
  if (session.waiting_for === PERMISSION) {
    return {
      ...base,
      kind: "permission",
      title: preview ? `${preview.tool}: ${preview.title || firstLine(preview.body)}` : "A tool call waits for approval",
      detail: preview ? firstLine(preview.body) : "",
    };
  }
  return { ...base, kind: "input", title: waitingLabel(session), detail: "" };
}

export function waitingItems(sessions: Session[]): Waiting[] {
  const recorded = sessions
    .flatMap((session) =>
      session.decisions.map(
        (decision): Waiting => ({
          key: decision.decision_id,
          session,
          kind: "decision",
          title: decision.header || "Decision",
          detail: decision.question,
          since: decision.created,
        }),
      ),
    )
    .sort((a, b) => a.since.localeCompare(b.since));
  const screens = sessions.flatMap((session) => onScreen(session) ?? []);
  return [...recorded, ...screens];
}

export function countMarks(sessions: Session[]): Record<Mark, number> {
  const counts: Record<Mark, number> = { blocked: 0, working: 0, done: 0, idle: 0 };
  for (const session of sessions) counts[markOf(session)] += 1;
  return counts;
}

export function byUrgency(sessions: Session[]): Session[] {
  return [...sessions].sort(
    (a, b) => RANK[markOf(a)] - RANK[markOf(b)] || displayName(a).localeCompare(displayName(b)),
  );
}

export function progress(session: Session): Progress | null {
  const recap = session.recap;
  if (!recap?.tasks_total) return null;
  return { done: recap.tasks_done, total: recap.tasks_total, current: recap.current_task };
}

export function lastWord(session: Session): string {
  const said = session.recap?.last_said || session.summary;
  if (said) return said;
  const lines = session.excerpt.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines.at(-1) ?? "";
}
