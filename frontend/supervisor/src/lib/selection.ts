import type { Session } from "./types";

export function pickSession(sessions: Session[], chosen: string): Session | null {
  return (
    sessions.find((session) => session.session_id === chosen) ??
    sessions.find((session) => session.group === "needs-you") ??
    sessions.find((session) => session.group === "working") ??
    sessions[0] ??
    null
  );
}
