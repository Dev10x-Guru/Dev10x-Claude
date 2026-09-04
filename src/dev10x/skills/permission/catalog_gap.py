"""Report catalog rules missing from a settings file (GH-1136).

The propagation defect this module answers was invisible for months
because ``ensure-base`` reported success while writing nothing: it
filtered the rendered catalog against ``~/.claude/settings.json`` and,
once global had been seeded, found everything "already covered". The
permission engine consults the *project* file when one exists (GH-47),
so 137 of 285 shipped rules were absent from every project file while
the maintenance log read clean.

Silence was the defect, so the fix ships a way to ask the question
directly: does this settings file carry the catalog? The answer is a
count per rule family, which is what a supervisor triaging friction
needs — "38 MCP tools missing" locates the gap, whereas a flat list of
137 strings does not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_FAMILY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mcp", re.compile(r"^mcp__")),
    ("skill", re.compile(r"^Skill\(")),
    ("read", re.compile(r"^Read\(")),
    ("edit", re.compile(r"^Edit\(")),
    ("write", re.compile(r"^Write\(")),
    ("git", re.compile(r"^Bash\(git\b")),
    ("gh", re.compile(r"^Bash\(gh\b")),
    ("dev10x-cli", re.compile(r"^Bash\((?:uvx )?dev10x\b")),
    ("plugin-script", re.compile(r"^Bash\(\S*(?:/tmp/Dev10x|CLAUDE_PLUGIN_ROOT)")),
    ("bash", re.compile(r"^Bash\(")),
)

UNCLASSIFIED_FAMILY = "other"


def rule_family(rule: str) -> str:
    """Classify a permission rule into a coarse family for gap reporting.

    Order matters: the ``bash`` pattern is a catch-all for ``Bash(...)``
    rules and must stay last among the Bash entries so ``git`` / ``gh`` /
    ``dev10x-cli`` win over it.
    """
    for name, pattern in _FAMILY_PATTERNS:
        if pattern.search(rule):
            return name
    return UNCLASSIFIED_FAMILY


@dataclass(frozen=True)
class CatalogGap:
    """Catalog rules absent from one settings file."""

    path: Path
    missing_allow: list[str] = field(default_factory=list)
    missing_deny: list[str] = field(default_factory=list)
    missing_ask: list[str] = field(default_factory=list)
    unreadable: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.missing_allow and not self.missing_deny and not self.missing_ask

    @property
    def total_missing(self) -> int:
        return len(self.missing_allow) + len(self.missing_deny) + len(self.missing_ask)


def _existing_rules(path: Path) -> tuple[set[str], set[str], set[str], str | None]:
    try:
        data = json.loads(path.read_text())
    except OSError as error:
        return set(), set(), set(), f"unreadable: {error}"
    except json.JSONDecodeError as error:
        return set(), set(), set(), f"invalid JSON: {error}"
    permissions = data.get("permissions", {})
    return (
        set(permissions.get("allow", [])),
        set(permissions.get("deny", [])),
        set(permissions.get("ask", [])),
        None,
    )


def compute_gap(
    *,
    path: Path,
    base_permissions: list[str],
    base_denies: list[str],
    base_asks: list[str] | None = None,
) -> CatalogGap:
    """Return the catalog rules that ``path`` does not carry.

    A file that cannot be read is reported as a gap carrying the whole
    catalog plus an ``unreadable`` reason — never as a clean result,
    since "we could not tell" and "nothing is missing" must not look
    alike to a caller deciding whether to backfill.

    ``base_asks`` (GH-1154) is optional so a caller predating the ask
    tier keeps its behaviour: an omitted ask catalog reports no ask gap
    rather than reporting every ask rule as missing.
    """
    asks = list(base_asks or [])
    allow, deny, ask, unreadable = _existing_rules(path)
    if unreadable is not None:
        return CatalogGap(
            path=path,
            missing_allow=list(base_permissions),
            missing_deny=list(base_denies),
            missing_ask=asks,
            unreadable=unreadable,
        )
    return CatalogGap(
        path=path,
        missing_allow=[rule for rule in base_permissions if rule not in allow],
        missing_deny=[rule for rule in base_denies if rule not in deny],
        missing_ask=[rule for rule in asks if rule not in ask],
    )


def _family_counts(rules: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule in rules:
        family = rule_family(rule)
        counts[family] = counts.get(family, 0) + 1
    return counts


def format_gap_report(gap: CatalogGap, *, verbose: bool = False) -> list[str]:
    """Render one file's gap as report lines, grouped by rule family."""
    lines = [str(gap.path)]
    if gap.unreadable is not None:
        lines.append(f"  WARNING: {gap.unreadable} — treating the whole catalog as missing")
    if gap.is_empty:
        lines.append("  0 missing allow / 0 missing deny / 0 missing ask")
        return lines

    lines.append(
        f"  {len(gap.missing_allow)} missing allow / {len(gap.missing_deny)} missing deny"
        f" / {len(gap.missing_ask)} missing ask"
    )
    for label, rules in (
        ("allow", gap.missing_allow),
        ("deny", gap.missing_deny),
        ("ask", gap.missing_ask),
    ):
        if not rules:
            continue
        counts = _family_counts(rules)
        for family in sorted(counts):
            lines.append(f"    {label}/{family}: {counts[family]}")
        if verbose:
            lines.extend(f"      + {rule}" for rule in rules)
    return lines
