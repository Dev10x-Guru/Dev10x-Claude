import type { View } from "./types";

const PINS_KEY = "supervisor.pins";
export const PROJECT_PINS_KEY = "supervisor.project-pins";
export const PROJECT_ORDER_KEY = "supervisor.project-order";
const HIDE_STOPPED_KEY = "supervisor.hide-stopped";

export function loadHideStopped(store: Store | null = storage()): boolean {
  return read(HIDE_STOPPED_KEY, store) === "1";
}

export function saveHideStopped(hide: boolean, store: Store | null = storage()): void {
  write(HIDE_STOPPED_KEY, hide ? "1" : "0", store);
}
const VIEW_KEY = "supervisor.view";
const AFTER_ANSWER_KEY = "supervisor.after-answer";

export type AfterAnswer = "stay" | "next";

export function loadAfterAnswer(store: Store | null = storage()): AfterAnswer {
  return read(AFTER_ANSWER_KEY, store) === "next" ? "next" : "stay";
}

export function saveAfterAnswer(choice: AfterAnswer, store: Store | null = storage()): void {
  write(AFTER_ANSWER_KEY, choice, store);
}

export interface Panel {
  key: string;
  min: number;
  max: number;
  fallback: number;
}

export const ASIDE: Panel = { key: "supervisor.aside-width", min: 200, max: 560, fallback: 288 };
export const SIDE: Panel = { key: "supervisor.side-width", min: 240, max: 760, fallback: 384 };
export const MODAL_WIDTH: Panel = { key: "supervisor.modal-width", min: 480, max: 1600, fallback: 832 };
export const MODAL_HEIGHT: Panel = { key: "supervisor.modal-height", min: 320, max: 1200, fallback: 560 };

type Store = Pick<Storage, "getItem" | "setItem">;

function storage(): Store | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

function read(key: string, store: Store | null): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(key: string, value: string, store: Store | null): void {
  try {
    store?.setItem(key, value);
  } catch {
    // A full or blocked store only costs the preference, never the page.
  }
}

export function loadList(key: string, store: Store | null = storage()): string[] {
  try {
    const parsed: unknown = JSON.parse(read(key, store) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function saveList(key: string, items: string[], store: Store | null = storage()): void {
  write(key, JSON.stringify(items), store);
}

export function loadPins(store: Store | null = storage()): string[] {
  return loadList(PINS_KEY, store);
}

export function savePins(pins: string[], store: Store | null = storage()): void {
  saveList(PINS_KEY, pins, store);
}

export function moveBefore(order: string[], item: string, before: string): string[] {
  if (item === before) return order;
  const rest = order.filter((entry) => entry !== item);
  const at = rest.indexOf(before);
  return at < 0 ? [...rest, item] : [...rest.slice(0, at), item, ...rest.slice(at)];
}

export function moveBy(order: string[], item: string, step: number): string[] {
  const from = order.indexOf(item);
  if (from < 0) return order;
  const to = Math.min(order.length - 1, Math.max(0, from + step));
  const rest = order.filter((entry) => entry !== item);
  return [...rest.slice(0, to), item, ...rest.slice(to)];
}

export function togglePin(pins: string[], key: string): string[] {
  return pins.includes(key) ? pins.filter((pin) => pin !== key) : [...pins, key];
}

export function loadView(store: Store | null = storage()): View {
  return read(VIEW_KEY, store) === "screen" ? "screen" : "transcript";
}

export function saveView(view: View, store: Store | null = storage()): void {
  write(VIEW_KEY, view, store);
}

export function clampWidth(panel: Panel, px: number): number {
  return Math.round(Math.min(panel.max, Math.max(panel.min, px)));
}

export function loadWidth(panel: Panel, store: Store | null = storage()): number {
  const value = Number(read(panel.key, store));
  return Number.isFinite(value) && value > 0 ? clampWidth(panel, value) : panel.fallback;
}

export function saveWidth(panel: Panel, px: number, store: Store | null = storage()): void {
  write(panel.key, String(clampWidth(panel, px)), store);
}
