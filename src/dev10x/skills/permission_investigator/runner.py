"""Domain entry points for `dev10x permission investigate` (GH-47, GH-525).

The command group's bodies used to open ``matrix.json``, build the
state envelope, and ``write_text`` inline. Per
``.claude/rules/script-domain-boundaries.md`` (GH-246 H3/H7) that
file read/mutate/write logic lives here instead, leaving the command
bodies as thin arg-parse + delegate + print shims.

Each function returns a result dict consumable by
``commands.permission._emit_result`` — ``messages`` (stdout lines),
``errors`` (stderr lines), and ``exit_code``. Path resolution (where
``matrix.json`` lives under ``/tmp``) stays in the command layer; the
functions below operate on explicit paths handed in by the caller.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dev10x.skills.permission_investigator import fixtures, load_matrix_from_state
from dev10x.skills.permission_investigator.matrix import RuleShape, generate_matrix
from dev10x.skills.permission_investigator.report import render_markdown_report


def _state_missing() -> dict[str, Any]:
    return {"errors": ["ERROR: state missing — run `prepare` first."], "exit_code": 1}


def prepare(*, workdir: Path, user_home: Path, default_workdir: Path) -> dict[str, Any]:
    """Materialize fixtures, snapshot settings, and persist matrix state.

    Writes ``matrix.json`` into ``workdir``. When ``workdir`` differs
    from ``default_workdir``, a redirect pointer is written at the
    default location so apply/record/report/restore can find the real
    state without re-passing ``--workdir``.
    """
    paths = fixtures.materialize_fixtures(workdir=workdir, user_home=user_home)

    snapshot_dir = workdir / "snapshots"
    fixtures.snapshot_settings(settings_path=paths.global_settings, snapshot_dir=snapshot_dir)
    fixtures.snapshot_settings(settings_path=paths.project_settings, snapshot_dir=snapshot_dir)

    matrix = generate_matrix()
    state = {
        "fixture": {
            "fixture_root": str(paths.fixture_root),
            "fixture_relpath": str(paths.fixture_relpath),
            "plugin_skill_file": str(paths.plugin_skill_file),
            "project_settings": str(paths.project_settings),
            "global_settings": str(paths.global_settings),
            "workdir": str(paths.workdir),
            "publisher_root": str(paths.publisher_root),
        },
        "cells": [
            {
                "cell_id": cell.cell_id,
                "shape": asdict(cell.shape),
                "location": cell.location,
            }
            for cell in matrix.cells
        ],
        "results": {},
    }
    real_state_path = workdir / "matrix.json"
    real_state_path.parent.mkdir(parents=True, exist_ok=True)
    real_state_path.write_text(json.dumps(state, indent=2))

    if workdir != default_workdir:
        default_state_path = default_workdir / "matrix.json"
        default_state_path.parent.mkdir(parents=True, exist_ok=True)
        default_state_path.write_text(json.dumps({"redirect": str(real_state_path)}, indent=2))

    return {
        "messages": [
            f"Workdir: {workdir}",
            f"Fixture: {paths.plugin_skill_file}",
            f"Cells: {len(matrix.cells)}",
        ],
        "exit_code": 0,
    }


def apply_cell(*, state_path: Path, cell_id: str, user_home: Path) -> dict[str, Any]:
    """Apply the rule shape for ``cell_id`` to its target settings file(s)."""
    if not state_path.is_file():
        return _state_missing()
    state = json.loads(state_path.read_text())

    cell = next((c for c in state["cells"] if c["cell_id"] == cell_id), None)
    if cell is None:
        return {"errors": [f"ERROR: unknown cell_id {cell_id}"], "exit_code": 1}

    shape = RuleShape(**cell["shape"])
    rule = shape.render(
        fixture_relpath=state["fixture"]["fixture_relpath"],
        user_home=str(user_home),
    )

    targets: list[Path] = []
    if cell["location"] in ("project", "both"):
        targets.append(Path(state["fixture"]["project_settings"]))
    if cell["location"] in ("global", "both"):
        targets.append(Path(state["fixture"]["global_settings"]))

    for target in targets:
        fixtures.apply_rule(rule=rule, target=target)

    return {
        "messages": [f"Applied rule: {rule}", f"Targets: {len(targets)}"],
        "exit_code": 0,
    }


def record_outcome(
    *,
    state_path: Path,
    cell_id: str,
    auto_approved: bool,
    error: str | None,
    notes: str,
) -> dict[str, Any]:
    """Record the outcome for one cell into the persisted matrix."""
    if not state_path.is_file():
        return _state_missing()
    state = json.loads(state_path.read_text())

    state.setdefault("results", {})[cell_id] = {
        "cell_id": cell_id,
        "auto_approved": bool(auto_approved),
        "prompted": not bool(auto_approved),
        "error": error,
        "notes": notes,
    }
    state_path.write_text(json.dumps(state, indent=2))
    return {"messages": [f"Recorded {cell_id}"], "exit_code": 0}


def restore(*, state_path: Path) -> dict[str, Any]:
    """Restore settings files from the pre-run snapshots and drop fixtures."""
    if not state_path.is_file():
        return {"messages": ["Nothing to restore — state missing."], "exit_code": 0}
    state = json.loads(state_path.read_text())
    snapshot_dir = Path(state["fixture"]["workdir"]) / "snapshots"

    messages: list[str] = []
    for key in ("global_settings", "project_settings"):
        target = Path(state["fixture"][key])
        snap = snapshot_dir / f"{target.name}.snapshot"
        if snap.is_file():
            fixtures.restore_settings(snapshot_path=snap, target_path=target)
            messages.append(f"Restored {target}")

    publisher_root_str = state["fixture"].get("publisher_root")
    if publisher_root_str:
        publisher_root = Path(publisher_root_str)
        if publisher_root.is_dir():
            shutil.rmtree(publisher_root)
            messages.append(f"Removed fixture publisher tree {publisher_root}")

    return {"messages": messages, "exit_code": 0}


def build_report(*, state_path: Path, output: str | None) -> dict[str, Any]:
    """Render the populated matrix as a markdown report."""
    if not state_path.is_file():
        return _state_missing()
    state = json.loads(state_path.read_text())

    rendered = render_markdown_report(load_matrix_from_state(state))
    if output:
        Path(output).write_text(rendered)
        return {"messages": [f"Wrote report to {output}"], "exit_code": 0}
    return {"messages": [rendered], "exit_code": 0}
