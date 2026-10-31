"""Prune never-matching rules from the userspace catalog copy (GH-1664).

``init`` copies the whole shipped catalog into ``~/.config/Dev10x/projects.yaml``
and the merge is shipped ∪ user, so a rule the plugin retired lives on in
the user's copy. GH-1472 retired the ``*``-before-``:*`` shapes because they
never match; one machine still carried 33 of them, and ``ensure-base``
refused and listed them on every run.

They are removed, not rewritten: the space form an allow rule would take
widens a grant that was never active (GH-1503). The file is hand-edited, so
the prune works line by line — a ``yaml.safe_dump`` round trip would strip
every comment the user wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dev10x.domain.file_locks import atomic_write_text, file_lock
from dev10x.skills.permission.backup import create_backup
from dev10x.skills.permission.star_prefix import is_unmatchable

_LIST_ITEM = re.compile(r"""^\s*-\s*(?P<quote>["']?)(?P<rule>Bash\(.*\))(?P=quote)\s*(?:\#.*)?$""")
_TOP_LEVEL_KEY = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):")
ALLOW_SECTION = "base_permissions"


@dataclass(frozen=True)
class CatalogPrune:
    removed: tuple[str, ...]
    backup: Path | None = None

    def describe(self, *, path: Path, dry_run: bool) -> list[str]:
        if not self.removed:
            return []
        verb = "Would remove" if dry_run else "Removed"
        messages = [
            f"\n{path}",
            f"  {verb} {len(self.removed)} catalog rule(s) with a `*` before `:*`"
            " — they never match (GH-1472):",
        ]
        messages.extend(f"    - {rule}" for rule in self.removed)
        return messages


def _unmatchable_rule(line: str) -> str | None:
    match = _LIST_ITEM.match(line)
    if match is None:
        return None
    rule = match.group("rule")
    return rule if is_unmatchable(rule) else None


def _prunable_lines(lines: list[str]) -> dict[int, str]:
    """Dead rules inside the allow tier only, by line index.

    A dead deny or ask is a guardrail; GH-1503 rewrites those to the space
    form rather than dropping them, so the prune never touches another
    top-level section.
    """
    section = ""
    prunable: dict[int, str] = {}
    for index, line in enumerate(lines):
        top_level = _TOP_LEVEL_KEY.match(line)
        if top_level is not None:
            section = top_level.group("key")
            continue
        rule = _unmatchable_rule(line) if section == ALLOW_SECTION else None
        if rule is not None:
            prunable[index] = rule
    return prunable


def prune_unmatchable_catalog_rules(*, config_path: Path, dry_run: bool) -> CatalogPrune:
    """Drop every allow-tier item whose rule can never match; keep all other lines."""
    if not config_path.is_file():
        return CatalogPrune(removed=())
    with file_lock(config_path):
        lines = config_path.read_text().splitlines(keepends=True)
        prunable = _prunable_lines(lines)
        removed = tuple(prunable[index] for index in sorted(prunable))
        if not removed or dry_run:
            return CatalogPrune(removed=removed)
        backup = create_backup(config_path)
        kept = "".join(line for index, line in enumerate(lines) if index not in prunable)
        atomic_write_text(config_path, kept)
    return CatalogPrune(removed=removed, backup=backup)


def prune_messages(*, config_path: Path, dry_run: bool) -> list[str]:
    """Run the prune and describe it; a failure is reported, never raised.

    The prune is an incidental pre-step of ``clean``. A locked, unreadable
    or unwritable catalog must not take down the settings cleanup that the
    user actually asked for.
    """
    try:
        pruned = prune_unmatchable_catalog_rules(config_path=config_path, dry_run=dry_run)
    except (OSError, UnicodeDecodeError) as error:
        return [f"  SKIP (cannot prune {config_path}): {error}"]
    return pruned.describe(path=config_path, dry_run=dry_run)


__all__ = ["CatalogPrune", "prune_messages", "prune_unmatchable_catalog_rules"]
