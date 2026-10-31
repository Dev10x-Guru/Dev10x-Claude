import type { ActionResult, Snapshot } from "./types";

export type Connection = "connecting" | "live" | "lost";

export function readToken(search: string = location.search): string {
  return new URLSearchParams(search).get("token") ?? "";
}

export async function post(
  path: string,
  body: Record<string, unknown>,
  token: string,
): Promise<ActionResult> {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Supervisor-Token": token },
      body: JSON.stringify(body),
    });
    const payload = (await response.json()) as ActionResult;
    return response.ok ? { ...payload, ok: true } : { ok: false, error: payload.error ?? `HTTP ${response.status}` };
  } catch {
    return { ok: false, error: "The supervisor daemon is not answering." };
  }
}

export function subscribe(
  token: string,
  onSnapshot: (snapshot: Snapshot) => void,
  onConnection: (state: Connection) => void,
): () => void {
  const source = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
  onConnection("connecting");
  source.addEventListener("snapshot", (event) => {
    onConnection("live");
    onSnapshot(JSON.parse((event as MessageEvent<string>).data) as Snapshot);
  });
  source.onerror = () => onConnection(source.readyState === EventSource.CLOSED ? "lost" : "connecting");
  return () => source.close();
}
