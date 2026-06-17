"""Canonical skill-script path resolution (GH-611).

Maps a skill *invocation name* to its on-disk directory using a scanned
:class:`~dev10x.skill_index.catalog.SkillCatalog` as the source of truth,
instead of constructing a path from the name. Path construction is the
documented failure mode (GH-488 evidence #7/#11): plugin skills strip the
namespace prefix from their directory (``Dev10x:git-commit`` lives at
``skills/git-commit/``) while personal skills may keep the colon in the
directory name (``~/.claude/skills/my:daily-yt/``). An agent that builds
``skills/<plugin>:<name>/`` therefore exits 127. A scan-backed resolver
never guesses — it returns the real directory of the matched ``SKILL.md``
— and it can disambiguate two skills that share a feature name across
different plugins.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.skill_index.builder import SkillEntry
from dev10x.skill_index.catalog import SkillCatalog


def feature_name(invocation_name: str) -> str:
    """Return the namespace-stripped feature name.

    ``Dev10x:git-commit`` -> ``git-commit``; ``my:daily-yt`` -> ``daily-yt``;
    a bare ``park`` -> ``park``. Only the final colon-delimited segment is
    significant — the leading segment is the plugin/personal namespace that
    the directory name may or may not retain.
    """
    return invocation_name.split(":")[-1].strip()


@dataclass(frozen=True)
class ResolvedSkill:
    """A skill invocation name located on disk."""

    entry: SkillEntry
    directory: Path

    @property
    def skill_file(self) -> Path:
        return self.directory / "SKILL.md"


@dataclass(frozen=True)
class SkillResolution:
    """Outcome of resolving one invocation name.

    The three states are mutually exclusive:

    - :attr:`is_resolved` — exactly one located match (``resolved`` set)
    - :attr:`is_ambiguous` — duplicate names; ``candidates`` lists each
    - :attr:`is_missing` — no entry matched, or the matches carried no
      on-disk ``source`` to locate
    """

    query: str
    resolved: ResolvedSkill | None = None
    candidates: tuple[ResolvedSkill, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.resolved is not None

    @property
    def is_ambiguous(self) -> bool:
        return self.resolved is None and len(self.candidates) > 1

    @property
    def is_missing(self) -> bool:
        return self.resolved is None and not self.candidates

    @property
    def directory(self) -> Path | None:
        """The resolved directory, or ``None`` when not uniquely resolved."""
        return self.resolved.directory if self.resolved is not None else None


@dataclass(frozen=True)
class SkillPathResolver:
    """Resolve invocation names to on-disk directories via a scanned catalog."""

    catalog: SkillCatalog = field(default_factory=SkillCatalog)

    @classmethod
    def from_dirs(cls, *, skill_dirs: Iterable[Path]) -> SkillPathResolver:
        """Build a resolver by scanning ``skill_dirs`` for ``SKILL.md`` files."""
        return cls(catalog=SkillCatalog.from_dirs(skill_dirs=skill_dirs))

    def resolve(self, *, name: str) -> SkillResolution:
        """Resolve ``name`` to a directory.

        Matching runs in precedence order — exact invocation key, then
        exact internal ``name:``, then namespace-stripped feature name.
        The most specific tier that matches anything decides the outcome,
        so a fully-qualified ``Plugin:feature`` resolves even when the bare
        ``feature`` would be ambiguous across plugins.
        """
        needle = name.strip()
        if not needle:
            return SkillResolution(query=name)

        for matcher in (self._match_key, self._match_name, self._match_feature):
            matches = matcher(needle=needle)
            if not matches:
                continue
            located = self._dedupe(
                located=[r for entry in matches if (r := self._locate(entry=entry))]
            )
            if len(located) == 1:
                return SkillResolution(query=name, resolved=located[0])
            if len(located) > 1:
                return SkillResolution(query=name, candidates=tuple(located))
            # The tier matched by name but nothing carried an on-disk source.
            return SkillResolution(query=name)
        return SkillResolution(query=name)

    def _match_key(self, *, needle: str) -> list[SkillEntry]:
        return [entry for entry in self.catalog.entries if entry.key == needle]

    def _match_name(self, *, needle: str) -> list[SkillEntry]:
        return [entry for entry in self.catalog.entries if entry.name == needle]

    def _match_feature(self, *, needle: str) -> list[SkillEntry]:
        target = feature_name(invocation_name=needle)
        return [
            entry
            for entry in self.catalog.entries
            if feature_name(invocation_name=entry.key) == target
        ]

    @staticmethod
    def _locate(*, entry: SkillEntry) -> ResolvedSkill | None:
        if entry.source is None:
            return None
        return ResolvedSkill(entry=entry, directory=entry.source.parent)

    @staticmethod
    def _dedupe(*, located: list[ResolvedSkill]) -> list[ResolvedSkill]:
        seen: set[Path] = set()
        unique: list[ResolvedSkill] = []
        for item in located:
            if item.directory in seen:
                continue
            seen.add(item.directory)
            unique.append(item)
        return unique
