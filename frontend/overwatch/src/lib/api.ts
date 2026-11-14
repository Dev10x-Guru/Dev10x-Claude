import type { ActionResult, ProjectDetail, SessionDetail, Snapshot } from "./types";

export type Connection = "connecting" | "live" | "lost";

export type TokenCheck = "ok" | "rejected" | "down";

export interface FoundToken {
  token: string;
  remembered: boolean;
}

const TOKEN_KEY = "overwatch.token";

export function readToken(search: string = location.search): string {
  return new URLSearchParams(search).get("token") ?? "";
}

export function browserStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function resolveToken(search: string, storage: Storage | null): FoundToken {
  const given = readToken(search);
  try {
    if (given) {
      storage?.setItem(TOKEN_KEY, given);
      return { token: given, remembered: false };
    }
    return { token: storage?.getItem(TOKEN_KEY) ?? "", remembered: true };
  } catch {
    return { token: given, remembered: false };
  }
}

export function forgetToken(storage: Storage | null): void {
  try {
    storage?.removeItem(TOKEN_KEY);
  } catch {
    // A blocked storage has nothing to forget.
  }
}

export async function checkToken(token: string): Promise<TokenCheck> {
  try {
    const response = await fetch("/api/sessions", { headers: { "X-Overwatch-Token": token } });
    return response.status === 403 ? "rejected" : "ok";
  } catch {
    return "down";
  }
}

export async function post(
  path: string,
  body: Record<string, unknown>,
  token: string,
): Promise<ActionResult> {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Overwatch-Token": token },
      body: JSON.stringify(body),
    });
    const payload = (await response.json()) as ActionResult;
    return response.ok ? { ...payload, ok: true } : { ok: false, error: payload.error ?? `HTTP ${response.status}` };
  } catch {
    return { ok: false, error: "The Overwatch daemon is not answering." };
  }
}

export async function fetchDetail(
  sessionId: string,
  token: string,
  screen: boolean,
): Promise<SessionDetail | null> {
  const query = `session_id=${encodeURIComponent(sessionId)}${screen ? "&screen=1" : ""}`;
  try {
    const response = await fetch(`/api/session?${query}`, {
      headers: { "X-Overwatch-Token": token },
    });
    return response.ok ? ((await response.json()) as SessionDetail) : null;
  } catch {
    return null;
  }
}

export async function fetchProject(root: string, token: string): Promise<ProjectDetail | string> {
  try {
    const response = await fetch(`/api/project?root=${encodeURIComponent(root)}`, {
      headers: { "X-Overwatch-Token": token },
    });
    const payload = (await response.json()) as ProjectDetail & { error?: string };
    return response.ok ? payload : (payload.error ?? `HTTP ${response.status}`);
  } catch {
    return "The Overwatch daemon is not answering.";
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
