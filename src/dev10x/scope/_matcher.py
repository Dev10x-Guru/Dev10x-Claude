"""Shared path-matching helper for norms/safeguards renderers (GH-170).

Per-entry matching (``**`` → ``*`` fnmatch semantics) is owned by
:meth:`dev10x.scope.index_parser.RuleEntry.matches`; this module only
selects which entries match any affected file.
"""

from __future__ import annotations

from dev10x.scope.index_parser import RuleEntry


def select_matching(
    *,
    entries: list[RuleEntry],
    affected_files: list[str],
) -> list[RuleEntry]:
    """Return entries whose any pattern matches any affected file."""

    return [entry for entry in entries if any(entry.matches(path=path) for path in affected_files)]
