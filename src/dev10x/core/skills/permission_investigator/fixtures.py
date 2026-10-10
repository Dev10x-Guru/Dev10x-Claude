"""Fixture materialization, settings snapshot, and restore.

Each investigation run materializes a deterministic fixture under
the user's HOME so tool-call probes have a real path to read or
execute. Settings files are snapshotted before any mutation and
restored on tear-down so the user's permission state is never
left dirty if a run fails.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

WORKDIR_NAMESPACE = "permission-investigator"


@dataclass(frozen=True)
class FixturePaths:
    """Filesystem layout for one investigation run."""

    workdir: Path
    fixture_root: Path
    fixture_relpath: str
    plugin_skill_file: Path
    project_settings: Path
    global_settings: Path
    publisher_root: Path

    def cleanup(self) -> None:
        if self.workdir.is_dir():
            shutil.rmtree(self.workdir)
        if self.publisher_root.is_dir():
            shutil.rmtree(self.publisher_root)


def materialize_fixtures(
    *,
    workdir: Path,
    user_home: Path,
    publisher: str = "Test-Org",
    plugin: str = "Investigator",
    version: str = "9.9.9",
    skill_name: str = "probe-skill",
) -> FixturePaths:
    """Create a controlled fixture tree under ``workdir``.

    Returns paths the dispatcher needs: a plugin-style skill file
    (under HOME so `~/...` rules resolve), a project-local settings
    stub, and a pointer to the user's global settings.
    """
    workdir.mkdir(parents=True, exist_ok=True)

    fixture_relpath = f".claude/plugins/cache/{publisher}/{plugin}/{version}/skills/{skill_name}"
    fixture_root = user_home / fixture_relpath
    fixture_root.mkdir(parents=True, exist_ok=True)
    plugin_skill_file = fixture_root / "SKILL.md"
    plugin_skill_file.write_text(
        f"# Probe — {publisher}/{plugin}/{version}\n\nFixture for permission investigation.\n"
    )

    publisher_root = user_home / ".claude" / "plugins" / "cache" / publisher

    project_settings = workdir / "project_settings.local.json"
    project_settings.write_text(json.dumps({"permissions": {"allow": []}}, indent=2))

    global_settings = user_home / ".claude" / "settings.json"

    return FixturePaths(
        workdir=workdir,
        fixture_root=fixture_root,
        fixture_relpath=f"{fixture_relpath}/SKILL.md",
        plugin_skill_file=plugin_skill_file,
        project_settings=project_settings,
        global_settings=global_settings,
        publisher_root=publisher_root,
    )


def snapshot_settings(*, settings_path: Path, snapshot_dir: Path) -> Path | None:
    """Save a copy of ``settings_path`` to ``snapshot_dir`` and return its path."""
    if not settings_path.is_file():
        return None
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{settings_path.name}.snapshot"
    shutil.copy2(settings_path, snapshot_path)
    return snapshot_path


def restore_settings(*, snapshot_path: Path, target_path: Path) -> None:
    """Replace ``target_path`` with ``snapshot_path`` (taken pre-mutation)."""
    if not snapshot_path.is_file():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot_path, target_path)


def apply_rule(
    *,
    rule: str,
    target: Path,
) -> None:
    """Append ``rule`` to ``target``'s permissions.allow list (idempotent).

    Creates the file with a minimal skeleton if it does not exist.
    """
    if target.is_file():
        data = json.loads(target.read_text())
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {"permissions": {"allow": []}}

    data.setdefault("permissions", {})
    data["permissions"].setdefault("allow", [])
    if rule not in data["permissions"]["allow"]:
        data["permissions"]["allow"].append(rule)
    target.write_text(json.dumps(data, indent=2) + "\n")


def remove_rule(
    *,
    rule: str,
    target: Path,
) -> None:
    """Remove ``rule`` from ``target``'s permissions.allow list."""
    if not target.is_file():
        return
    data = json.loads(target.read_text())
    allow = data.get("permissions", {}).get("allow", [])
    if rule in allow:
        allow.remove(rule)
        target.write_text(json.dumps(data, indent=2) + "\n")
