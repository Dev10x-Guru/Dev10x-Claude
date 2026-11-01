import type { Session } from "./types";

const QUESTION_TOOL = "AskUserQuestion";

export function asksQuestion(session: Session): boolean {
  if (session.status !== "waiting") return false;
  return session.decisions.length > 0 || session.preview?.tool === QUESTION_TOOL;
}

export function nextQuestion(sessions: Session[], currentId: string): string {
  const at = sessions.findIndex((session) => session.session_id === currentId);
  const rotated = [...sessions.slice(at + 1), ...sessions.slice(0, Math.max(at, 0))];
  return rotated.find((session) => session.session_id !== currentId && asksQuestion(session))?.session_id ?? "";
}

export function pickSession(sessions: Session[], chosen: string): Session | null {
  return (
    sessions.find((session) => session.session_id === chosen) ??
    sessions.find((session) => session.group === "needs-you") ??
    sessions.find((session) => session.group === "working") ??
    sessions[0] ??
    null
  );
}
