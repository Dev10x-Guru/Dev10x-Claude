"""Milestone initiative-prefix registry (GH-1690).

`references/milestone-naming.md` requires every `<INIT>` prefix to be
registered before its first milestone is created. The rule lived only in
prose, and on 2026-10-31 ten of fifteen open-milestone prefixes were
missing from the table. These pure functions let `milestone_create`
refuse an unregistered prefix at the point it would be introduced.
"""

from __future__ import annotations

import re

REGISTRY_RELPATH = "references/milestone-naming.md"

_REGISTRY_HEADING = "## Registered Initiative Prefixes"
_REGISTRY_ROW = re.compile(r"^\| `(?P<prefix>[A-Z]+)` \|", re.MULTILINE)
_TITLE_PREFIX = re.compile(r"^(?P<prefix>[A-Z]{2,6})(?:-M\d+)?: \S")


def parse_registered_prefixes(text: str) -> frozenset[str]:
    _, _, section = text.partition(_REGISTRY_HEADING)
    table, _, _ = section.partition("\n## ")
    return frozenset(_REGISTRY_ROW.findall(table))


def title_prefix(title: str) -> str | None:
    match = _TITLE_PREFIX.match(title)
    return match.group("prefix") if match else None


def unregistered_prefix_error(*, title: str, registered: frozenset[str]) -> str | None:
    prefix = title_prefix(title=title)
    if prefix is None:
        return (
            f"Milestone title {title!r} does not start with an initiative prefix. "
            f"Use `<INIT>: <outcome>` with a prefix registered in {REGISTRY_RELPATH} "
            "§ Registered Initiative Prefixes (GH-1690)."
        )
    if prefix in registered:
        return None
    return (
        f"Milestone prefix {prefix!r} is not registered. Add this row to "
        f"{REGISTRY_RELPATH} § Registered Initiative Prefixes before creating "
        f"the milestone: | `{prefix}` | <initiative> | active | (GH-1690)."
    )
