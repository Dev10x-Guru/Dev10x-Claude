import type { Session } from "./types";

export type Mark = "blocked" | "working" | "done" | "idle";

export interface Folder {
  root: string;
  sessions: Session[];
}

export interface Project {
  name: string;
  mark: Mark;
  count: number;
  folders: Folder[];
}

const RANK: Record<Mark, number> = { blocked: 0, working: 1, done: 2, idle: 3 };

export function markOf(session: Session): Mark {
  if (session.group === "needs-you") return "blocked";
  if (session.group === "working") return "working";
  return session.status === "idle" ? "idle" : "done";
}

function strongest(marks: Mark[]): Mark {
  return marks.reduce<Mark>((best, mark) => (RANK[mark] < RANK[best] ? mark : best), "idle");
}

function byMarkThenName<T>(items: T[], mark: (item: T) => Mark, name: (item: T) => string): T[] {
  return [...items].sort((a, b) => RANK[mark(a)] - RANK[mark(b)] || name(a).localeCompare(name(b)));
}

export function buildTree(sessions: Session[]): Project[] {
  const projects = new Map<string, Map<string, Session[]>>();
  for (const session of sessions) {
    const name = session.workspace.project || session.cwd;
    const root = session.workspace.root || session.cwd;
    const folders = projects.get(name) ?? new Map<string, Session[]>();
    folders.set(root, [...(folders.get(root) ?? []), session]);
    projects.set(name, folders);
  }
  const built = [...projects].map(([name, folders]): Project => {
    const all = [...folders.values()].flat();
    const folderList = [...folders].map(([root, items]) => ({
      root,
      sessions: byMarkThenName(items, markOf, (session) => session.name),
    }));
    return {
      name,
      mark: strongest(all.map(markOf)),
      count: all.length,
      folders: byMarkThenName(
        folderList,
        (folder) => strongest(folder.sessions.map(markOf)),
        (folder) => folder.root,
      ),
    };
  });
  return byMarkThenName(built, (project) => project.mark, (project) => project.name);
}

export function matches(session: Session, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [session.name, session.callsign, session.cwd, session.workspace.branch, session.workspace.issue]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}
