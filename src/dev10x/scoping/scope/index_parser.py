"""Parse ``.claude/rules/INDEX.md`` routing table into rule entries.

The INDEX.md file declares a path-aware routing table that maps
file-pattern globs to rule files and review agents. The
autopopulator (``render_norms`` / ``render_safeguards``) walks
this table to discover which rules apply to a scope's affected
files.

Format expected (Markdown table, GH-flavored):

    | File Pattern | Primary Agent | Required References |
    |---|---|---|
    | `**/*.py`, `**/*.sh` | reviewer-generic, ... | ... |

This parser is intentionally lenient — INDEX.md is hand-edited
and the goal is robust matching, not strict schema validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(frozen=True)
class RuleEntry:
    """One rule discovered from INDEX.md.

    ``patterns`` are fnmatch-style globs lifted from the table's
    "File Pattern" column. ``source`` is the table row's main
    reference (rule file path or agent spec) — used as the
    rendered Markdown link target.
    """

    patterns: tuple[str, ...]
    source: str
    description: str

    def matches(self, *, path: str) -> bool:
        """True when ``path`` matches any of this entry's patterns.

        ``**`` is treated as ``*`` after a one-time substitution, matching
        the loose convention INDEX.md uses (e.g. ``**/*.py``). Owning the
        match here keeps the pattern-iteration loop out of callers.
        """
        for pattern in self.patterns:
            normalized = pattern.replace("**/", "*/").replace("**", "*")
            if fnmatch(path, pattern) or fnmatch(path, normalized):
                return True
        return False


_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")


def parse_index(*, index_path: Path) -> list[RuleEntry]:
    """Return rule entries lifted from INDEX.md's routing tables.

    Raises ``FileNotFoundError`` if ``index_path`` does not exist —
    callers (renderers) should catch and fall back to an empty
    "no matched rules" rendering.
    """

    text = index_path.read_text()
    entries: list[RuleEntry] = []
    in_table = False
    saw_header_separator = False

    for line in text.splitlines():
        match = _TABLE_ROW_RE.match(line)
        if not match:
            in_table = False
            saw_header_separator = False
            continue

        cells = [cell.strip() for cell in match.group(1).split("|")]

        if not in_table:
            if any("File Pattern" in cell for cell in cells):
                in_table = True
                saw_header_separator = False
            continue

        if not saw_header_separator:
            if all(set(cell) <= {"-", ":", " "} for cell in cells):
                saw_header_separator = True
            continue

        if len(cells) < 2:
            continue

        patterns = tuple(_BACKTICK_RE.findall(cells[0]))
        if not patterns:
            continue

        source = cells[1] if len(cells) > 1 else ""
        description = cells[2] if len(cells) > 2 else ""
        entries.append(
            RuleEntry(
                patterns=patterns,
                source=source.strip(),
                description=description.strip(),
            )
        )

    return entries
