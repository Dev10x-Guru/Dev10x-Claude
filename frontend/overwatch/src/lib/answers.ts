export const ANSWERS_KEY = "overwatch.answers";
export const ANSWERS_KEPT = 5;

export interface Answer {
  id: string;
  session_id: string;
  session_name: string;
  question: string;
  options: string[];
  chosen: string;
  at: string;
}

type Store = Pick<Storage, "getItem" | "setItem">;

function storage(): Store | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function isAnswer(value: unknown): value is Answer {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Record<string, unknown>;
  return (
    ["id", "session_id", "session_name", "question", "chosen", "at"].every((key) => typeof entry[key] === "string") &&
    Array.isArray(entry.options) &&
    entry.options.every((option) => typeof option === "string")
  );
}

export function loadAnswers(store: Store | null = storage()): Answer[] {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(ANSWERS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isAnswer).slice(0, ANSWERS_KEPT) : [];
  } catch {
    return [];
  }
}

export function saveAnswers(answers: Answer[], store: Store | null = storage()): void {
  try {
    store?.setItem(ANSWERS_KEY, JSON.stringify(answers));
  } catch {
    // A full or blocked store only costs the history, never the answer itself.
  }
}

export function remember(answers: Answer[], entry: Answer): Answer[] {
  return [entry, ...answers.filter((answer) => answer.id !== entry.id)].slice(0, ANSWERS_KEPT);
}

export function changeAnswer(answers: Answer[], id: string, chosen: string, at: string): Answer[] {
  const found = answers.find((answer) => answer.id === id);
  return found ? remember(answers, { ...found, chosen, at }) : answers;
}

export function correction(answer: Answer, chosen: string): string {
  return [
    `The supervisor changed their answer to an earlier question: "${answer.question}".`,
    `Earlier answer: "${answer.chosen}". New answer: "${chosen}".`,
    "Act on the new answer and undo anything that only made sense under the earlier one.",
  ].join("\n");
}
