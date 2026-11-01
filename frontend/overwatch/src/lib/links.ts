import type { Workspace } from "./types";

export interface Link {
  match: RegExp;
  href: string;
}

export interface Piece {
  text: string;
  href: string;
}

export const USAGE_URL = "https://claude.ai/new#settings/usage";

function escape(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function statusLinks(workspace: Workspace): Link[] {
  const links: Link[] = [];
  if (workspace.pr && workspace.pr_url) {
    links.push({ match: new RegExp(`PR\\s?#${workspace.pr}\\b`), href: workspace.pr_url });
  }
  if (workspace.issue && workspace.issue_url) {
    links.push({ match: new RegExp(`(?<![\\w/-])${escape(workspace.issue)}(?![\\w-])`), href: workspace.issue_url });
  }
  if (workspace.branch && workspace.repo_url) {
    links.push({
      match: new RegExp(escape(workspace.branch)),
      href: `${workspace.repo_url}/tree/${workspace.branch.split("/").map(encodeURIComponent).join("/")}`,
    });
  }
  links.push({ match: /\b(?:5h|7d) \d+%(?: ↻\S+)?/, href: USAGE_URL });
  return links;
}

export function linkify(text: string, links: Link[]): Piece[] {
  let best: { index: number; length: number; href: string } | null = null;
  for (const link of links) {
    const found = link.match.exec(text);
    if (found && (best === null || found.index < best.index)) {
      best = { index: found.index, length: found[0].length, href: link.href };
    }
  }
  if (best === null) return text ? [{ text, href: "" }] : [];
  return [
    ...(best.index > 0 ? [{ text: text.slice(0, best.index), href: "" }] : []),
    { text: text.slice(best.index, best.index + best.length), href: best.href },
    ...linkify(text.slice(best.index + best.length), links),
  ];
}
