import { changeAnswer, loadAnswers, remember, saveAnswers, type Answer } from "./answers";

export const recent = $state<{ answers: Answer[] }>({ answers: loadAnswers() });

export function record(entry: Answer): void {
  recent.answers = remember(recent.answers, entry);
  saveAnswers(recent.answers);
}

export function revise(id: string, chosen: string): void {
  recent.answers = changeAnswer(recent.answers, id, chosen, new Date().toISOString());
  saveAnswers(recent.answers);
}
