// GH-1844

export type WorkStatus = "queued" | "awaiting_approval" | "claimed" | "done" | "rejected";

export const WORK_STATUSES: WorkStatus[] = ["awaiting_approval", "queued", "claimed", "done", "rejected"];

export const STATUS_LABELS: Record<WorkStatus, string> = {
  awaiting_approval: "Awaiting approval",
  queued: "Queued",
  claimed: "Claimed",
  done: "Done",
  rejected: "Rejected",
};

export const BUS_ROUTE = "#/bus";

export interface BusEvent {
  id: number;
  type: string;
  space: string;
  sender: string;
  source: string;
  event_time: string;
  received_at: string;
  thread: string | null;
  untrusted_text: string;
}

export interface BusCommand {
  id: number;
  event_id: number;
  actor: string;
  verb: string;
  authorized: boolean;
  outcome: string | null;
  reason: string;
  work_item_id: number | null;
  created_at: string;
}

export interface BusWorkItem {
  id: number;
  kind: string;
  status: WorkStatus;
  claimed_by: string | null;
  claimed_until: string | null;
  attempts: number;
  result: string | null;
  event_type: string;
  space: string;
  sender: string;
  thread: string | null;
  untrusted_text: string;
  created_at: string;
}

export interface BusGap {
  id: number;
  space: string;
  from: string;
  to: string;
  reason: string;
}

export interface BusMember {
  chat_user: string;
  login: string | null;
}

export interface BusAllowlist {
  config: string;
  owner: BusMember | null;
  trusted: BusMember[];
  error: string | null;
}

export interface BusBoard {
  store: string;
  exists: boolean;
  queue: Record<WorkStatus, number>;
  expired_leases: number;
  gaps: BusGap[];
  allowlist: BusAllowlist;
  events: BusEvent[];
  commands: BusCommand[];
  work_items: BusWorkItem[];
}

const THREAD = /^spaces\/([A-Za-z0-9_-]+)\/threads\/([A-Za-z0-9_-]+)$/;
const DB_TIME = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$/;

export function isBusRoute(hash: string): boolean {
  return hash === BUS_ROUTE || hash === `${BUS_ROUTE}/`;
}

export function threadUrl(thread: string | null): string {
  const match = THREAD.exec(thread ?? "");
  if (!match) return "";
  return `https://chat.google.com/room/${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}`;
}

export function member(entry: BusMember | null): string {
  if (!entry) return "none";
  return entry.login ? `${entry.login} (${entry.chat_user})` : entry.chat_user;
}

export function busTime(value: string): string {
  const match = DB_TIME.exec(value);
  return match ? `${match[1]} ${match[2]} UTC` : value;
}

export function byStatus(items: BusWorkItem[]): { status: WorkStatus; items: BusWorkItem[] }[] {
  return WORK_STATUSES.map((status) => ({ status, items: items.filter((item) => item.status === status) })).filter(
    (group) => group.items.length > 0,
  );
}

export async function fetchBoard(token: string): Promise<BusBoard | string> {
  try {
    const response = await fetch("/api/chatbus", { headers: { "X-Overwatch-Token": token } });
    const payload = (await response.json()) as BusBoard & { error?: string };
    return response.ok ? payload : (payload.error ?? `HTTP ${response.status}`);
  } catch {
    return "The Overwatch daemon is not answering.";
  }
}
