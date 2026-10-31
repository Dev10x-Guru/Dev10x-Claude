import type { View } from "./types";

const PINS_KEY = "supervisor.pins";
const VIEW_KEY = "supervisor.view";
const ASIDE_KEY = "supervisor.aside-width";

export const ASIDE_MIN_PX = 200;
export const ASIDE_MAX_PX = 560;
export const ASIDE_DEFAULT_PX = 288;

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

export function clampAside(px: number): number {
  return Math.round(Math.min(ASIDE_MAX_PX, Math.max(ASIDE_MIN_PX, px)));
}

export function loadAsideWidth(store: Store | null = storage()): number {
  const value = Number(read(ASIDE_KEY, store));
  return Number.isFinite(value) && value > 0 ? clampAside(value) : ASIDE_DEFAULT_PX;
}

export function saveAsideWidth(px: number, store: Store | null = storage()): void {
  write(ASIDE_KEY, String(clampAside(px)), store);
}
