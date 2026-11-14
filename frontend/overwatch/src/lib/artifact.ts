import { post } from "./api";
import type { ActionResult } from "./types";

export type Tone = "ok" | "warn" | "bad" | "info";

export interface ToneText {
  text: string;
  tone?: Tone;
}

export type TableCell = string | ToneText;

export interface ClaimBlock {
  type: "claim";
  text: string;
}

export interface ProseBlock {
  type: "prose";
  paragraphs: string[];
}

export interface CalloutBlock {
  type: "callout";
  tone: Tone;
  text: string;
}

export interface KvBlock {
  type: "kv";
  items: { key: string; value: string }[];
}

export interface TableBlock {
  type: "table";
  columns: string[];
  rows: TableCell[][];
}

export interface PillsBlock {
  type: "pills";
  items: { text: string; tone: Tone }[];
}

export interface StatsBlock {
  type: "stats";
  items: { label: string; value: string; note?: string }[];
}

export interface MermaidBlock {
  type: "mermaid";
  source: string;
}

export interface DraftBlock {
  type: "draft";
  label: string;
  text: string;
}

export interface EvidenceBlock {
  type: "evidence";
  items: { claim: string; ref: string; check?: string }[];
}

export interface DecisionsBlock {
  type: "decisions";
  items: { question: string; owner?: string; control?: string }[];
}

export interface ButtonBlock {
  type: "button";
  id: string;
  label: string;
  tone?: "primary" | "danger" | "default";
  value?: string;
}

export interface ChoiceBlock {
  type: "choice";
  id: string;
  label: string;
  options: string[];
  multi?: boolean;
}

export interface FormField {
  name: string;
  label: string;
  kind: "text" | "textarea" | "select";
  options?: string[];
}

export interface FormBlock {
  type: "form";
  id: string;
  label: string;
  fields: FormField[];
  submit?: string;
}

export type ControlBlock = ButtonBlock | ChoiceBlock | FormBlock;

export type Block =
  | ClaimBlock
  | ProseBlock
  | CalloutBlock
  | KvBlock
  | TableBlock
  | PillsBlock
  | StatsBlock
  | MermaidBlock
  | DraftBlock
  | EvidenceBlock
  | DecisionsBlock
  | ControlBlock;

export type ControlValue = string | string[] | Record<string, string>;

export interface ArtifactView {
  id: string;
  label: string;
  group?: string;
  badge?: string;
  blocks: Block[];
}

export interface ArtifactOwner {
  session_id: string;
  name: string;
  cwd?: string;
}

export interface ArtifactShare {
  publisher: string;
  url: string;
  at: string;
}

export interface ArtifactEvent {
  event_id?: string;
  kind?: "control" | "share" | string;
  revision?: number;
  control_id?: string;
  label?: string;
  value?: unknown;
  publisher?: string;
  at?: string;
  channel?: string;
}

export interface ArtifactDocument {
  schema: string;
  id: string;
  title: string;
  description?: string;
  revision: number;
  updated_at: string;
  owner: ArtifactOwner;
  meta?: { as_of?: string; sources?: string; asked_by?: string };
  views: ArtifactView[];
  shares?: ArtifactShare[];
  events?: ArtifactEvent[];
}

export interface ArtifactIndexEntry {
  id: string;
  title: string;
  owner: { session_id: string; name: string };
  revision: number;
  updated_at: string;
  owner_live: boolean;
}

export interface Publisher {
  id: string;
  label: string;
}

export interface ArtifactRoute {
  id: string;
  view: string;
}

const ROUTE = /^#\/a\/([^/]+)(?:\/([^/]+))?\/?$/;

export function parseRoute(hash: string): ArtifactRoute | null {
  const match = ROUTE.exec(hash);
  if (!match) return null;
  try {
    return { id: decodeURIComponent(match[1]), view: match[2] ? decodeURIComponent(match[2]) : "" };
  } catch {
    return null;
  }
}

export function formatRoute(id: string, view = ""): string {
  const base = `#/a/${encodeURIComponent(id)}`;
  return view ? `${base}/${encodeURIComponent(view)}` : base;
}

export function pickView(document: ArtifactDocument, view: string): ArtifactView {
  return document.views.find((each) => each.id === view) ?? document.views[0];
}

export interface NavGroup {
  group: string;
  views: ArtifactView[];
}

export function navGroups(views: ArtifactView[]): NavGroup[] {
  const groups: NavGroup[] = [];
  for (const view of views) {
    const name = view.group ?? "";
    const found = groups.find((each) => each.group === name);
    if (found) found.views.push(view);
    else groups.push({ group: name, views: [view] });
  }
  return groups;
}

export function findControl(document: ArtifactDocument, id: string): ControlBlock | null {
  for (const view of document.views) {
    for (const block of view.blocks) {
      if ((block.type === "button" || block.type === "choice" || block.type === "form") && block.id === id) {
        return block;
      }
    }
  }
  return null;
}

export function standaloneBlocks(view: ArtifactView): Block[] {
  const answered = new Set(
    view.blocks.flatMap((block) =>
      block.type === "decisions" ? block.items.map((item) => item.control ?? "") : [],
    ),
  );
  return view.blocks.filter((block) => !("id" in block && answered.has(block.id)));
}

export function deliveryReport(result: ActionResult, what: string): string {
  return result.recorded === false
    ? `${what}, but the page could not record it; do not send it again`
    : what;
}

export async function fetchArtifact(id: string, token: string): Promise<ArtifactDocument | string> {
  try {
    const response = await fetch(`/api/artifact?id=${encodeURIComponent(id)}`, {
      headers: { "X-Overwatch-Token": token },
    });
    const payload = (await response.json()) as ArtifactDocument & { error?: string };
    return response.ok ? payload : (payload.error ?? `HTTP ${response.status}`);
  } catch {
    return "The Overwatch daemon is not answering.";
  }
}

export interface ControlEvent {
  artifact_id: string;
  revision: number;
  control_id: string;
  value: ControlValue;
}

export function sendControl(event: ControlEvent, token: string): Promise<ActionResult> {
  return post("/artifact/event", { ...event }, token);
}

export function share(artifactId: string, publisher: string, token: string): Promise<ActionResult> {
  return post("/artifact/share", { artifact_id: artifactId, publisher }, token);
}

export type SentControls = Record<string, number>;

export function sentKey(artifactId: string, controlId: string): string {
  return `${artifactId}:${controlId}`;
}

export function isPending(
  document: Pick<ArtifactDocument, "id" | "revision" | "events">,
  controlId: string,
  sent: SentControls,
): boolean {
  if (sent[sentKey(document.id, controlId)] === document.revision) return true;
  return (document.events ?? []).some(
    (event) =>
      (event.kind ?? "control") === "control" &&
      event.control_id === controlId &&
      event.revision === document.revision,
  );
}

export type ControlState = "ready" | "sending" | "pending" | "offline" | "error";

export interface ControlFacts {
  live: boolean;
  pending: boolean;
  sending: boolean;
  error: string;
}

export function controlState({ live, pending, sending, error }: ControlFacts): ControlState {
  if (sending) return "sending";
  if (pending) return "pending";
  if (!live) return "offline";
  return error ? "error" : "ready";
}

export function describeValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, each]) => `${key}: ${String(each)}`)
      .join("; ");
  }
  return value === undefined ? "" : String(value);
}

export function cellText(cell: TableCell): ToneText {
  return typeof cell === "string" ? { text: cell } : cell;
}
