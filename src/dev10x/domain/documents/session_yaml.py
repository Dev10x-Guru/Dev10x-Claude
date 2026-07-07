"""Persistence boundary for the split session config (GH-774).

Two sibling documents under ``.claude/Dev10x/`` with different lifetimes:

- :class:`ConfigYamlDocument` — ``config.yaml``, **durable** repo
  preferences (``friction_level``, ``active_modes``, and the ADR-0016
  gate keys). Personal, gitignored, and **copied** source→worktree by
  the ``post-checkout`` hook so every worktree of a repo shares them.
- :class:`SessionYamlDocument` — ``session.yaml``, **ephemeral**
  per-worktree state (``branch``, ``tickets``, continuation prompts).
  Seeded fresh per worktree, never carried between them.

Splitting the two escapes Claude Code's ``.claude/`` self-edit gate: the
hook provisions both files, so no runtime ``Write(.claude/…)`` happens on
the hot path (GH-774 comment 3). ``SessionYamlDocument`` stays the single
read facade — its durable readers prefer ``config.yaml`` and fall back to
a pre-split ``session.yaml`` that still carries the durable keys, so the
migration is transparent (ADR-0007 D3 keeps Policy Rules I/O-free).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.friction_level import FrictionLevel


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Tolerantly load a YAML mapping, degrading to ``{}`` on any failure.

    A missing, unreadable, or malformed file — including an undecodable
    one (``ValueError`` covers ``UnicodeDecodeError``) — must degrade to
    the soft fallbacks rather than crash the SessionStart hook.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class ConfigYamlDocument:
    """Reader/writer for durable prefs at ``.claude/Dev10x/config.yaml`` (GH-774)."""

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "config.yaml"

    def data(self) -> dict[str, Any]:
        return _load_yaml_mapping(self.path)

    @staticmethod
    def render(*, friction_level: str = "guided", active_modes: list[str] | None = None) -> str:
        """Render the canonical ``config.yaml`` body (durable prefs)."""
        return (
            "# Dev10x durable repo preferences (GH-774) — friction level and\n"
            "# active modes. Gitignored + copied to each worktree by the\n"
            "# post-checkout hook. Ephemeral per-worktree state (branch,\n"
            "# tickets) lives in the sibling session.yaml.\n"
            f"friction_level: {friction_level}  # strict | guided | adaptive\n"
            f"active_modes: {active_modes or []!r}\n"
        )

    def write(
        self, *, friction_level: str = "guided", active_modes: list[str] | None = None
    ) -> None:
        """Write ``config.yaml`` for this toplevel, creating parents as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(friction_level=friction_level, active_modes=active_modes))


@dataclass(frozen=True)
class SessionYamlDocument:
    """Read facade for the session config; writer for ephemeral ``session.yaml``."""

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "session.yaml"

    def _load(self) -> dict[str, Any]:
        """Load the ephemeral ``session.yaml`` mapping."""
        return _load_yaml_mapping(self.path)

    def _durable(self) -> dict[str, Any]:
        """Durable prefs: ``config.yaml`` wins; a pre-split ``session.yaml`` is
        the migration fallback (durable keys historically lived there, GH-774)."""
        return {**self._load(), **ConfigYamlDocument(toplevel=self.toplevel).data()}

    def durable_prefs(self) -> dict[str, Any]:
        """Explicit durable prefs (config wins, pre-split session fallback).

        Unlike the typed readers this applies **no** defaulting, so ``None``
        distinguishes "unset" from "explicitly guided" — the migration seam
        ``dev10x session seed`` uses to lift a pre-split ``session.yaml``'s
        durable keys into ``config.yaml`` without overwriting them.
        """
        return self._durable()

    def read_friction_level(self) -> FrictionLevel:
        """Return the session friction level, defaulting on any read failure."""
        return FrictionLevel.from_yaml(self._durable().get("friction_level"))

    def read_active_modes(self) -> list[str]:
        """Return the active-modes list, or an empty list when unset/invalid."""
        modes = self._durable().get("active_modes")
        return modes if isinstance(modes, list) else []

    def read_friction_and_modes(self) -> tuple[FrictionLevel, list[str]]:
        """Return ``(friction_level, active_modes)`` from the durable prefs."""
        data = self._durable()
        level = FrictionLevel.from_yaml(data.get("friction_level"))
        modes = data.get("active_modes")
        return level, (modes if isinstance(modes, list) else [])

    def read_gate_policy_inputs(self) -> dict[str, Any]:
        """Return the resolver inputs for ``gate_policy`` (ADR-0016).

        All of these are **durable** — read from ``config.yaml`` with the
        pre-split ``session.yaml`` fallback. Two input styles coexist
        (ADR-0016 D-4): new-style ``gate_preset`` / ``gate_overlays`` name a
        preset + overlays directly; when absent, the legacy keys
        (``friction_level``, ``active_modes``, ``walk_away``) feed
        :func:`dev10x.domain.gate_policy.legacy_session_mapping`. Either way
        ``gate_overrides`` carries per-toggle session overrides.
        """
        data = self._durable()
        modes = data.get("active_modes")
        overrides = data.get("gate_overrides")
        preset = data.get("gate_preset")
        overlays = data.get("gate_overlays")
        return {
            "friction_level": FrictionLevel.from_yaml(data.get("friction_level")).value,
            "active_modes": modes if isinstance(modes, list) else [],
            "walk_away": bool(data.get("walk_away", False)),
            "gate_overrides": overrides if isinstance(overrides, dict) else {},
            "gate_preset": preset if isinstance(preset, str) else None,
            "gate_overlays": overlays if isinstance(overlays, list) else [],
        }

    def read_session_identity(self) -> dict[str, Any]:
        """Return the persisted session identity for staleness comparison.

        Ephemeral — read from ``session.yaml`` **only**, never ``config.yaml``:
        the ``branch`` the session was pinned to and the ``tickets`` it was
        working. Missing/invalid values degrade to ``None`` / ``[]`` so a bare
        file reads as identity-less (and therefore stale — the safe direction).
        work-on Phase 0 writes these keys on plan approval (GH-755).
        """
        data = self._load()
        branch = data.get("branch")
        tickets = data.get("tickets")
        return {
            "branch": branch if isinstance(branch, str) else None,
            "tickets": [t for t in tickets if isinstance(t, str)]
            if isinstance(tickets, list)
            else [],
        }

    @staticmethod
    def render_ephemeral() -> str:
        """Render a fresh ephemeral ``session.yaml`` stub (no durable keys).

        Seeded per worktree; work-on fills ``branch`` / ``tickets`` at
        runtime. Durable prefs live in the sibling ``config.yaml`` (GH-774).
        """
        return (
            "# Dev10x ephemeral per-worktree session state (GH-774) — branch,\n"
            "# tickets, continuation prompts. Seeded fresh per worktree; never\n"
            "# copied between them. Durable repo preferences live in the\n"
            "# sibling config.yaml.\n"
        )

    def write_ephemeral(self) -> None:
        """Write a fresh ephemeral ``session.yaml`` stub, creating parents."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render_ephemeral())


__all__ = ["ConfigYamlDocument", "SessionYamlDocument"]
