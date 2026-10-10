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

from dev10x.domain.common.policy import Policy, PolicyAssessment, PolicySource
from dev10x.domain.common.policy_resolution import attach_assessments
from dev10x.skills.permission_investigator import fixtures, load_matrix_from_state
from dev10x.skills.permission_investigator.matrix import Matrix, RuleShape, generate_matrix
from dev10x.skills.permission_investigator.policy_report import (
    investigator_assessment,
    render_policy_report,
)
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
            "user_home": str(user_home),
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


def _render_investigator_assessments(
    *,
    matrix: Matrix,
    fixture_relpath: str,
    user_home: str,
) -> list[str]:
    """Render recorded matrix outcomes as typed Policy assessment lines (PAP-5, GH-802).

    Each cell that recorded an outcome becomes an
    :func:`investigator_assessment` (``works`` / ``prompts`` / ``error`` /
    ``unknown``) keyed by the rule signature its shape renders to. Cells
    sharing a signature (same shape at different locations) accumulate under
    one entry via :func:`attach_assessments`, so the report references each
    tested rule as a typed :class:`Policy` — signature, tier, source, effect —
    instead of the pre-PAP shape-only prose.
    """
    records: dict[str, list[PolicyAssessment]] = {}
    ordered_signatures: list[str] = []
    for cell in matrix.cells:
        result = matrix.results.get(cell.cell_id)
        if result is None:
            continue
        signature = cell.shape.render(fixture_relpath=fixture_relpath, user_home=user_home)
        note = cell.location if not result.notes else f"{cell.location}: {result.notes}"
        if signature not in records:
            records[signature] = []
            ordered_signatures.append(signature)
        records[signature].append(investigator_assessment(status=str(result.status), note=note))
    if not ordered_signatures:
        return []
    policies = [
        Policy.from_rule_str(signature, tier=0, source=PolicySource.PLUGIN_DEFAULT)
        for signature in ordered_signatures
    ]
    attached = attach_assessments(
        policies=policies,
        records={signature: tuple(items) for signature, items in records.items()},
    )
    return render_policy_report(policies=attached)


def build_report(*, state_path: Path, output: str | None) -> dict[str, Any]:
    """Render the populated matrix as a markdown report.

    The markdown outcome table is followed by a PAP-5 policy-assessment
    section (GH-802): every recorded cell outcome is emitted as a typed
    :class:`~dev10x.domain.common.policy.PolicyAssessment` and rendered
    against the rule it judged via
    :func:`~dev10x.skills.permission_investigator.policy_report.render_policy_report`.
    """
    if not state_path.is_file():
        return _state_missing()
    state = json.loads(state_path.read_text())

    matrix = load_matrix_from_state(state)
    rendered = render_markdown_report(matrix)

    fixture = state.get("fixture", {})
    assessment_lines = _render_investigator_assessments(
        matrix=matrix,
        fixture_relpath=fixture.get("fixture_relpath", ""),
        user_home=fixture.get("user_home", ""),
    )
    if assessment_lines:
        rendered = (
            f"{rendered}\n## Policy Assessments (PAP-5)\n\n" + "\n".join(assessment_lines) + "\n"
        )

    if output:
        Path(output).write_text(rendered)
        return {"messages": [f"Wrote report to {output}"], "exit_code": 0}
    return {"messages": [rendered], "exit_code": 0}
