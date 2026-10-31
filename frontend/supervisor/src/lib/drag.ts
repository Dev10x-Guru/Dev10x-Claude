export const SESSION_MIME = "application/x-supervisor-session";
export const PROJECT_MIME = "application/x-supervisor-project";

export function carriesSession(types: readonly string[] | undefined): boolean {
  return !!types?.includes(SESSION_MIME);
}

export function carriesProject(types: readonly string[] | undefined): boolean {
  return !!types?.includes(PROJECT_MIME);
}

export function droppedPeer(data: string, current: string): string {
  const peer = data.trim();
  return peer && peer !== current ? peer : "";
}
