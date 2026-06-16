"""Skill catalog aggregate (audit finding D7).

Wraps the front-matter builder (:mod:`dev10x.skill_index.builder`) in a
queryable aggregate so callers can list entries or look one up by name
without re-scanning the skill directories or re-implementing the
key/name match. ``scan_skill_dirs`` returns a flat sorted list; this
aggregate adds the ``lookup`` capability that a bare list lacked.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from dev10x.skill_index.builder import SkillEntry, scan_skill_dirs


@dataclass(frozen=True)
class SkillCatalog:
    """An immutable, queryable collection of parsed skill entries."""

    entries: tuple[SkillEntry, ...] = ()

    @classmethod
    def from_dirs(cls, *, skill_dirs: Iterable[Path]) -> SkillCatalog:
        """Build a catalog by scanning ``skill_dirs`` for ``SKILL.md`` files."""
        return cls(entries=tuple(scan_skill_dirs(skill_dirs=skill_dirs)))

    def list(self) -> list[SkillEntry]:
        """Return all entries (sorted by key, as the builder produced them)."""
        return list(self.entries)

    def lookup(self, *, name: str) -> SkillEntry | None:
        """Find an entry by its menu key, falling back to its raw name.

        Returns ``None`` when ``name`` is blank or matches nothing. Key
        matches win over name matches so the invocation-name a caller
        types resolves before an internal ``name:`` collision.
        """
        needle = name.strip()
        if not needle:
            return None
        for entry in self.entries:
            if entry.key == needle:
                return entry
        for entry in self.entries:
            if entry.name == needle:
                return entry
        return None
