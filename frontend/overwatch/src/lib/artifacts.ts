import type { ArtifactBlock, ArtifactDocument, ArtifactSummary, FormField, Tone } from "./types";

export const BLOCK_TYPES = [
  "summary",
  "claim",
  "decisions",
  "kv",
  "table",
  "pills",
  "stats",
  "draft",
  "evidence",
  "button",
  "choice",
  "form",
] as const;

const TONES: readonly string[] = ["ok", "warn", "bad", "info"] satisfies Tone[];
const CONTROL_TYPES: readonly string[] = ["button", "choice", "form"];

export type ControlValue = null | string | string[] | Record<string, string>;

export function isKnownBlock(block: { type?: unknown }): block is ArtifactBlock {
  return typeof block.type === "string" && (BLOCK_TYPES as readonly string[]).includes(block.type);
}

export function isControl(block: ArtifactBlock): boolean {
  return CONTROL_TYPES.includes(block.type);
}

export function toneClass(tone: unknown): string {
  return typeof tone === "string" && TONES.includes(tone) ? `tone-${tone}` : "";
}

export function emptyForm(fields: FormField[]): Record<string, string> {
  return Object.fromEntries(fields.map((field) => [field.name, ""]));
}

export function missingRequired(fields: FormField[], values: Record<string, string>): string[] {
  return fields.filter((field) => field.required && !(values[field.name] ?? "").trim()).map((field) => field.label);
}

export function toggleOption(selected: string[], option: string, options: string[]): string[] {
  const next = selected.includes(option) ? selected.filter((item) => item !== option) : [...selected, option];
  return options.filter((item) => next.includes(item));
}

export function eventBody(
  document: ArtifactDocument,
  controlId: string,
  value: ControlValue,
): Record<string, unknown> {
  return { artifact_id: document.id, control_id: controlId, value, revision: document.revision };
}

export function isStale(document: ArtifactDocument | null, summary: ArtifactSummary | undefined): boolean {
  return Boolean(document && summary && summary.revision !== document.revision);
}

export async function fetchArtifact(artifactId: string, token: string): Promise<ArtifactDocument | string> {
  try {
    const response = await fetch(`/api/artifact?id=${encodeURIComponent(artifactId)}`, {
      headers: { "X-Overwatch-Token": token },
    });
    const payload = (await response.json()) as ArtifactDocument & { error?: string };
    return response.ok ? payload : (payload.error ?? `HTTP ${response.status}`);
  } catch {
    return "The Overwatch daemon is not answering.";
  }
}
