"""Render the Safeguards section of a ticket-scope document (GH-170).

Safeguards are invariants and validation rules that must hold
AFTER the change ships. Sources:

1. ``.claude/rules/INDEX.md`` rules whose source path matches
   security / validation / schema keywords
2. ``CLAUDE.md`` lines that contain safeguard-shaped guidance
   (security, validation, never/must keywords)
3. Hook deny rules from ``.claude/settings.local.json`` /
   ``.claude/settings.json``

Per ADR 0005: render at generation time. Callers inject the
returned Markdown under the ``## Safeguards`` heading.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dev10x.scope._matcher import select_matching
from dev10x.scope.index_parser import parse_index

_HEADER = "<!-- Auto-populated by dev10x.scope.safeguards_renderer at scope-render time. -->"
_EMPTY = "No safeguards matched. Manual additions only."

_SAFEGUARD_KEYWORDS = (
    "security",
    "validation",
    "schema",
    "gate",
    "deny",
    "never",
    "must",
    "auth",
    "permission",
    "safety",
)
_NEVER_LINE_RE = re.compile(
    r"^\s*[-*]?\s*\*?\*?(Never|Must|Always|Do not|Don't|MUST|NEVER)\b",
    flags=re.IGNORECASE,
)


def render_safeguards(
    *,
    affected_files: list[str],
    index_path: Path,
    claude_md_path: Path | None = None,
    settings_paths: list[Path] | None = None,
) -> str:
    """Return Markdown for the Safeguards section."""

    parts: list[str] = [_HEADER, ""]
    has_content = False

    rule_lines = _matched_rule_lines(affected_files=affected_files, index_path=index_path)
    if rule_lines:
        has_content = True
        parts.append("**Rule-based safeguards** (from `.claude/rules/INDEX.md`):")
        parts.extend(rule_lines)
        parts.append("")

    if claude_md_path is not None:
        claude_lines = _claude_md_safeguards(path=claude_md_path)
        if claude_lines:
            has_content = True
            parts.append("**CLAUDE.md guidance**:")
            parts.extend(claude_lines)
            parts.append("")

    if settings_paths:
        deny_lines = _hook_deny_rules(paths=settings_paths)
        if deny_lines:
            has_content = True
            parts.append("**Hook deny rules** (commands blocked at runtime):")
            parts.extend(deny_lines)
            parts.append("")

    if not has_content:
        return _EMPTY

    return "\n".join(parts).rstrip()


def _matched_rule_lines(
    *,
    affected_files: list[str],
    index_path: Path,
) -> list[str]:
    try:
        entries = parse_index(index_path=index_path)
    except FileNotFoundError:
        return []

    matched = select_matching(entries=entries, affected_files=affected_files)
    seen: set[str] = set()
    out: list[str] = []
    for entry in matched:
        haystack = f"{entry.source} {entry.description}".lower()
        if not any(kw in haystack for kw in _SAFEGUARD_KEYWORDS):
            continue
        if entry.source in seen:
            continue
        seen.add(entry.source)
        patterns = ", ".join(f"`{p}`" for p in entry.patterns)
        out.append(f"- **{entry.source}** — enforces safeguards for {patterns}")
    return out


def _claude_md_safeguards(*, path: Path) -> list[str]:
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _NEVER_LINE_RE.match(stripped):
            out.append(f"- {stripped.lstrip('-* ').rstrip()}")
        if len(out) >= 10:
            break
    return out


def _hook_deny_rules(*, paths: list[Path]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        deny = data.get("permissions", {}).get("deny", [])
        for rule in deny:
            if isinstance(rule, str) and rule not in seen:
                seen.add(rule)
                out.append(f"- `{rule}`")
    return out
