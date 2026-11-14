export type Route = { kind: "session"; sessionId: string } | { kind: "artifact"; artifactId: string };

const ARTIFACT_PREFIX = "artifact/";

function decode(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return "";
  }
}

export function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  if (raw.startsWith(ARTIFACT_PREFIX)) {
    return { kind: "artifact", artifactId: decode(raw.slice(ARTIFACT_PREFIX.length)) };
  }
  return { kind: "session", sessionId: decode(raw) };
}

export function routeHash(route: Route): string {
  return route.kind === "artifact"
    ? `#${ARTIFACT_PREFIX}${encodeURIComponent(route.artifactId)}`
    : `#${encodeURIComponent(route.sessionId)}`;
}
