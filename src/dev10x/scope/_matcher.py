"""Shared path-matching helper for norms/safeguards renderers (GH-170).

Uses ``fnmatch`` semantics over POSIX paths. ``**`` is treated as
``*`` after a one-time substitution, matching the loose convention
INDEX.md uses (e.g. ``**/*.py``).
"""

from __future__ import annotations

from fnmatch import fnmatch

from dev10x.scope.index_parser import RuleEntry


def select_matching(
    *,
    entries: list[RuleEntry],
    affected_files: list[str],
) -> list[RuleEntry]:
    """Return entries whose any pattern matches any affected file."""

    matched: list[RuleEntry] = []
    for entry in entries:
        for pattern in entry.patterns:
            normalized = pattern.replace("**/", "*/").replace("**", "*")
            if any(fnmatch(path, pattern) or fnmatch(path, normalized) for path in affected_files):
                matched.append(entry)
                break
    return matched
