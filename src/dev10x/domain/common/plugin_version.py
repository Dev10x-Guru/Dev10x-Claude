"""PluginVersion value object — canonical ``major.minor.patch`` semver.

Eliminates the ``_version_tuple()`` helper triplicated across
``domain/install_version.py``, ``skills/permission/clean_project_files.py``,
and ``skills/permission/update_paths.py``, and the two divergent
``VERSION_PATTERN`` regexes (one ``re.IGNORECASE``, one not; capturing
groups differ) that each re-embedded the ``\\d+\\.\\d+\\.\\d+`` literal
(audit finding GH-506 — 2026-06-10).

Two parse paths exist on purpose:

* :meth:`PluginVersion.parse` is strict (``^\\d+\\.\\d+\\.\\d+$``) and is
  the right choice when the input is a known-good version string.
* :meth:`PluginVersion.sort_key` is lenient and replaces the historical
  ``_version_tuple`` sort key for scanning version-named directories
  whose names are not guaranteed to be strict semver.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

SEMVER_PATTERN = r"\d+\.\d+\.\d+"
SEMVER_RE = re.compile(rf"^{SEMVER_PATTERN}$")


@total_ordering
@dataclass(frozen=True)
class PluginVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, value: str) -> PluginVersion:
        if not isinstance(value, str) or not SEMVER_RE.match(value):
            msg = f"Invalid plugin version: {value!r}. Expected 'major.minor.patch'."
            raise ValueError(msg)
        major, minor, patch = (int(part) for part in value.split("."))
        return cls(major=major, minor=minor, patch=patch)

    @classmethod
    def try_parse(cls, value: str) -> PluginVersion | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def sort_key(cls, value: str) -> tuple[int, ...]:
        """Lenient sort key for version-named directories.

        Preserves the historical ``_version_tuple`` behaviour: split on
        ``.``, cast each segment to ``int``, and fall back to ``(0,)`` on
        any non-numeric segment. Use this when sorting directory names
        that may not be strict semver (e.g. scanning the plugin cache).
        """
        try:
            return tuple(int(part) for part in value.split("."))
        except ValueError:
            return (0,)

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __lt__(self, other: PluginVersion) -> bool:
        if not isinstance(other, PluginVersion):
            return NotImplemented
        return self.as_tuple() < other.as_tuple()
