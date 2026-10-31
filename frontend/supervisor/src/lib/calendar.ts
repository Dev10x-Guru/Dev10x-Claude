export interface Day {
  key: string;
  day: number;
  inMonth: boolean;
}

export interface Range {
  start: string;
  end: string;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function keyOf(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : dayKey(date);
}

export function monthGrid(year: number, month: number): Day[][] {
  const first = new Date(year, month, 1);
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - lead);
  const weeks: Day[][] = [];
  for (let week = 0; week < 6; week += 1) {
    const days: Day[] = [];
    for (let weekday = 0; weekday < 7; weekday += 1) {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + week * 7 + weekday);
      days.push({ key: dayKey(date), day: date.getDate(), inMonth: date.getMonth() === month });
    }
    if (week > 3 && !days.some((day) => day.inMonth)) break;
    weeks.push(days);
  }
  return weeks;
}

export function pick(range: Range, key: string): Range {
  if (!range.start || range.end) return { start: key, end: "" };
  return key < range.start ? { start: key, end: range.start } : { start: range.start, end: key };
}

export function inRange(key: string, range: Range): boolean {
  if (!range.start) return true;
  const end = range.end || range.start;
  return key >= range.start && key <= end;
}

export function countByDay(isos: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const iso of isos) {
    const key = keyOf(iso);
    if (key) counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}
