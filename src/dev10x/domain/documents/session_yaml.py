"""SessionYamlDocument — the persistence boundary for ``session.yaml``.

Document archetype (ADR-0007 / ADR-0008): owns reads of
``.claude/Dev10x/session.yaml`` so that Policy Rules stay free of file
I/O (the ADR-0007 D3 invariant). Rules and queries receive the parsed
``FrictionLevel`` and ``active_modes`` values from this Document rather
than opening the file inside ``apply()`` themselves.

Replaces the in-rule reads previously performed by
``ReadFrictionLevelRule`` (GH-515) and ``BuildAutonomyReassuranceRule``
(GH-513). A missing, unreadable, or malformed file yields the soft
fallbacks — ``FrictionLevel.default()`` and an empty modes list — so
callers never have to branch on read failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.friction_level import FrictionLevel


@dataclass(frozen=True)
class SessionYamlDocument:
    """Reader for ``.claude/Dev10x/session.yaml`` under a repo toplevel."""

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = yaml.safe_load(self.path.read_text())
        except (OSError, ValueError, yaml.YAMLError):
            # ValueError covers UnicodeDecodeError on an undecodable file —
            # a corrupt session.yaml must degrade to defaults, never crash
            # the SessionStart hook (matches the prior broad fallback).
            return {}
        return data if isinstance(data, dict) else {}

    def read_friction_level(self) -> FrictionLevel:
        """Return the session friction level, defaulting on any read failure."""
        return FrictionLevel.from_yaml(self._load().get("friction_level"))

    def read_active_modes(self) -> list[str]:
        """Return the active-modes list, or an empty list when unset/invalid."""
        modes = self._load().get("active_modes")
        return modes if isinstance(modes, list) else []

    def read_friction_and_modes(self) -> tuple[FrictionLevel, list[str]]:
        """Return ``(friction_level, active_modes)`` from a single file read."""
        data = self._load()
        level = FrictionLevel.from_yaml(data.get("friction_level"))
        modes = data.get("active_modes")
        return level, (modes if isinstance(modes, list) else [])

    @staticmethod
    def render(*, friction_level: str = "guided", active_modes: list[str] | None = None) -> str:
        """Render the canonical ``session.yaml`` body.

        The single source of truth for the file's shape — ``dev10x init``
        (interactive and ``--non-interactive``) routes its writes here
        instead of duplicating the template inline (audit N19).
        """
        return (
            "# Dev10x session config — consumed by work-on, verify-acc-dod, and\n"
            "# the PreCompact recovery hook.\n"
            f"friction_level: {friction_level}  # strict | guided | adaptive\n"
            f"active_modes: {active_modes or []!r}\n"
        )

    def write(
        self, *, friction_level: str = "guided", active_modes: list[str] | None = None
    ) -> None:
        """Write ``session.yaml`` for this toplevel, creating parents as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(friction_level=friction_level, active_modes=active_modes))


__all__ = ["SessionYamlDocument"]
