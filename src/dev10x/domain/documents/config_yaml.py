"""Per-repo durable prefs, ``.claude/Dev10x/config.yaml`` (GH-774).

Retired by ADR-0018 in favour of the global
:mod:`dev10x.domain.documents.friction_yaml`, and still read as a
one-cycle migration fallback. Also home to the playbook axis of
``Dev10x:friction-setup`` (:func:`set_playbook_modes`), which writes a
per-skill playbook rather than a session document. Split out of
``session_yaml.py`` by GH-1431.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.yaml_mapping import load_yaml_mapping
from dev10x.domain.file_locks import atomic_write_text, file_lock

#: Synthetic active-mode name under which ``Dev10x:friction-setup`` records
#: per-step skips it chose. The resolver honors step ``skip`` actions from any
#: active mode's ``mode_extensions`` (references/execution-modes.md resolution
#: 3b/3d), so a project-scoped step skip needs no new plumbing.
FRICTION_SETUP_SKIP_MODE = "friction-setup-skips"


@dataclass(frozen=True)
class ConfigYamlDocument:
    """Legacy per-repo durable prefs at ``.claude/Dev10x/config.yaml`` (GH-774).

    Retired by ADR-0018 in favor of the global :class:`FrictionYamlDocument`;
    still read as a one-cycle migration fallback for repos not yet present in
    ``friction.yaml``. ``upgrade-cleanup`` / ``plugin-doctor`` fold it in.
    """

    toplevel: str

    @property
    def path(self) -> Path:
        return Path(self.toplevel) / ".claude" / "Dev10x" / "config.yaml"

    def data(self) -> dict[str, Any]:
        return load_yaml_mapping(self.path)

    @staticmethod
    def render(
        *,
        friction_level: str = "guided",
        active_modes: list[str] | None = None,
        allowed_overlays: list[str] | None = None,
    ) -> str:
        """Render the canonical ``config.yaml`` body (durable prefs).

        ``allowed_overlays`` is emitted only when explicitly provided so the
        canonical body is byte-identical to the pre-GH-805 shape when the repo
        has not opted into the overlay guard — an omitted key reads back as
        ``None`` (permissive) via ``session_yaml._coerce_allowed_overlays``.
        """
        body = (
            "# Dev10x durable repo preferences (GH-774) — friction level and\n"
            "# active modes. Gitignored + copied to each worktree by the\n"
            "# post-checkout hook. Ephemeral per-worktree state (branch,\n"
            "# tickets) lives in the sibling session.yaml.\n"
            f"friction_level: {friction_level}  # strict | guided | adaptive\n"
            f"active_modes: {active_modes or []!r}\n"
        )
        if allowed_overlays is not None:
            body += (
                "# GH-805: local repo-character overlay allow-list. Any session\n"
                "# overlay not named here (e.g. solo-maintainer) is dropped before\n"
                "# gate resolution and flagged at SessionStart. An empty list\n"
                "# honors no high-autonomy overlay — correct for a team repo.\n"
                "# Omit the key entirely to allow every overlay (back-compat).\n"
                f"allowed_overlays: {list(allowed_overlays)!r}\n"
            )
        return body


def set_playbook_modes(
    *,
    skill: str,
    active_modes: list[str],
    skip_steps: list[str] | None = None,
    home: Path | None = None,
) -> Path:
    """Write the playbook axis of ``Dev10x:friction-setup`` to a global playbook (GH-886).

    Persists ``active_modes`` (the modes the supervisor enabled) into
    ``~/.config/Dev10x/playbooks/<skill>.yaml`` — the tier-2 project playbook the
    work-on resolver reads (instructions.md Phase 3 step 6). ``skip_steps`` names
    play-step subjects to always drop (e.g. ``"Draft Job Story"``); they are
    recorded as ``mode_extensions`` step ``skip`` actions under the synthetic
    :data:`FRICTION_SETUP_SKIP_MODE`, which is appended to ``active_modes`` so the
    resolver applies them (no new plumbing — execution-modes resolution 3b/3d).

    Concurrency-safe (exclusive lock + atomic write, GH-827 / ADR-0011) and
    idempotent — ``active_modes`` is replaced wholesale on each run. Returns the
    file written.

    ``skill`` is interpolated into the playbook filename, so it is validated
    against ``[A-Za-z0-9_-]+`` first: without this a value like
    ``../../../../tmp/evil`` would traverse outside the playbooks directory and
    write an arbitrary file (a manipulated CLI invocation / prompt injection).
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", skill):
        raise ValueError(
            f"invalid skill name {skill!r}: expected [A-Za-z0-9_-]+ (no path separators)"
        )
    base = home or Dev10xConfigDir.home()
    target = base / "playbooks" / f"{skill}.yaml"
    modes = list(active_modes)
    with file_lock(target):
        doc = load_yaml_mapping(target)
        if skip_steps:
            extensions = doc.get("mode_extensions")
            extensions = dict(extensions) if isinstance(extensions, dict) else {}
            extensions[FRICTION_SETUP_SKIP_MODE] = {
                "steps": {subject: {"skip": True} for subject in skip_steps}
            }
            doc["mode_extensions"] = extensions
            if FRICTION_SETUP_SKIP_MODE not in modes:
                modes.append(FRICTION_SETUP_SKIP_MODE)
        doc["active_modes"] = modes
        atomic_write_text(target, yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    return target


__all__ = [
    "FRICTION_SETUP_SKIP_MODE",
    "ConfigYamlDocument",
    "set_playbook_modes",
]
