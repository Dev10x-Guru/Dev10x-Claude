"""Render the Norms section of a ticket-scope document (GH-170).

Norms are project rules that the change MUST follow — style,
naming, testing, and pattern conventions discoverable from
``.claude/rules/INDEX.md``.

Per ADR 0005: render at generation time, not at scope-save time.
The caller passes the scope's affected-files list; the renderer
walks INDEX.md, path-matches, and emits Markdown ready to inject
under the ``## Norms`` heading.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.scope._matcher import select_matching
from dev10x.scope.index_parser import parse_index

_HEADER = (
    "<!-- Auto-populated by dev10x.scope.norms_renderer at scope-render time. -->"
    "\nMatched project rules (from `.claude/rules/INDEX.md`):"
)
_EMPTY_BODY = "No project rules matched the affected files for this scope."


def render_norms(
    *,
    affected_files: list[str],
    index_path: Path,
    rules_root: Path | None = None,
) -> str:
    """Return Markdown for the Norms section.

    ``rules_root`` (default: parent of ``index_path``) is the
    directory used to build relative links to matched rule files
    so they remain navigable from the rendered scope document.
    """

    if rules_root is None:
        rules_root = index_path.parent

    try:
        entries = parse_index(index_path=index_path)
    except FileNotFoundError:
        return _EMPTY_BODY

    matched = select_matching(entries=entries, affected_files=affected_files)
    if not matched:
        return _EMPTY_BODY

    lines = [_HEADER, ""]
    seen: set[str] = set()
    for entry in matched:
        key = entry.source
        if key in seen:
            continue
        seen.add(key)
        patterns = ", ".join(f"`{p}`" for p in entry.patterns)
        lines.append(f"- **{entry.source}** — applies to {patterns}")
        if entry.description:
            lines.append(f"  - {entry.description}")
    return "\n".join(lines)
