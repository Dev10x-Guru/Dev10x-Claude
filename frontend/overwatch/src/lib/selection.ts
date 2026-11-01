import type { Session } from "./types";

const QUESTION_TOOL = "AskUserQuestion";
export const ACK_GRACE_MS = 30_000;

export interface Sent {
  key: string;
  at: number;
}

export type SentAnswers = Record<string, Sent>;

export function asksQuestion(session: Session): boolean {
  if (session.status !== "waiting") return false;
  return session.decisions.length > 0 || session.preview?.tool === QUESTION_TOOL;
}

export function questionKey(session: Session): string {
  if (session.decisions.length) return session.decisions.map((decision) => decision.decision_id).join(",");
  const prompt = session.prompt;
  return prompt ? [prompt.question, ...prompt.options.map((option) => option.label)].join("\n") : "";
}

export function awaitingAck(session: Session, sent: SentAnswers): Sent | null {
  const entry = sent[session.session_id];
  return entry && asksQuestion(session) && entry.key === questionKey(session) ? entry : null;
}

export function pruneSent(sessions: Session[], sent: SentAnswers): SentAnswers {
  return Object.fromEntries(
    sessions.flatMap((session) => {
      const entry = awaitingAck(session, sent);
      return entry ? [[session.session_id, entry]] : [];
    }),
  );
}

export function nextQuestion(sessions: Session[], currentId: string, sent: SentAnswers = {}, now = 0): string {
  const at = sessions.findIndex((session) => session.session_id === currentId);
  const rotated = [...sessions.slice(at + 1), ...sessions.slice(0, Math.max(at, 0))];
  const fresh = (session: Session): boolean => {
    const entry = awaitingAck(session, sent);
    return !entry || now - entry.at >= ACK_GRACE_MS;
  };
  return (
    rotated.find((session) => session.session_id !== currentId && asksQuestion(session) && fresh(session))
      ?.session_id ?? ""
  );
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
