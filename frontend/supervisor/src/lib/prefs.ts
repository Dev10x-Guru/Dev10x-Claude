import type { View } from "./types";

const PINS_KEY = "supervisor.pins";
const VIEW_KEY = "supervisor.view";

export interface Panel {
  key: string;
  min: number;
  max: number;
  fallback: number;
}

export const ASIDE: Panel = { key: "supervisor.aside-width", min: 200, max: 560, fallback: 288 };
export const SIDE: Panel = { key: "supervisor.side-width", min: 240, max: 760, fallback: 384 };

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

export function loadPins(store: Store | null = storage()): string[] {
  try {
    const parsed: unknown = JSON.parse(read(PINS_KEY, store) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

export function savePins(pins: string[], store: Store | null = storage()): void {
  write(PINS_KEY, JSON.stringify(pins), store);
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
