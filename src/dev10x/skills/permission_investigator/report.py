"""Aggregate matrix outcomes into a markdown report and delta.

The report consumes a populated :class:`Matrix` (results recorded
by the dispatcher) plus the current ``base_permissions`` shipped
by ``plugin-maintenance``. It produces:

1. A grouped outcome matrix per dimension.
2. A list of currently-shipped rules whose shape matches a row
   marked "prompts" — these are the friction-causing entries.
3. A list of suggested replacements drawn from rows marked "works".
"""

from __future__ import annotations

from dataclasses import dataclass

from dev10x.skills.permission_investigator.matrix import (
    Matrix,
    MatrixResult,
    PathPrefix,
    WildcardShape,
)


@dataclass
class Delta:
    ineffective_rules: list[str]
    suggested_rules: list[str]


def aggregate_results(matrix: Matrix) -> dict[str, list[MatrixResult]]:
    """Group results by status (works / prompts / error / unknown)."""
    grouped: dict[str, list[MatrixResult]] = {
        "works": [],
        "prompts": [],
        "error": [],
        "unknown": [],
    }
    cell_index = {cell.cell_id: cell for cell in matrix.cells}
    for cell_id, result in matrix.results.items():
        if cell_id not in cell_index:
            continue
        grouped.setdefault(result.status, []).append(result)
    return grouped


def render_markdown_report(matrix: Matrix) -> str:
    """Render the matrix as a markdown table grouped by tool kind."""
    grouped = aggregate_results(matrix)

    lines: list[str] = ["# Permission Pattern Investigation"]
    lines.append("")
    seen, total = matrix.coverage()
    lines.append(f"Cells executed: **{seen}/{total}**")
    lines.append("")

    lines.append("## Outcome counts")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    for status in ("works", "prompts", "error", "unknown"):
        lines.append(f"| {status} | {len(grouped.get(status, []))} |")
    lines.append("")

    lines.append("## Per-cell results")
    lines.append("")
    lines.append("| Cell | Tool | Prefix | Wildcard | Location | Status | Notes |")
    lines.append("|------|------|--------|----------|----------|--------|-------|")
    for cell in matrix.cells:
        result = matrix.results.get(cell.cell_id)
        status = result.status if result else "(not run)"
        notes = (result.notes if result else "").replace("|", "\\|")
        lines.append(
            f"| `{cell.cell_id}` | {cell.shape.tool} | {cell.shape.prefix} | "
            f"{cell.shape.wildcard} | {cell.location} | {status} | {notes} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def compute_delta(
    *,
    matrix: Matrix,
    base_permissions: list[str],
) -> Delta:
    """Identify shipped rules whose shape failed in the matrix.

    A rule is flagged ineffective when at least one matrix cell with
    a matching wildcard/prefix shape was recorded as ``prompts``.
    """
    prompting_shapes = _shapes_for_status(matrix=matrix, status="prompts")
    working_shapes = _shapes_for_status(matrix=matrix, status="works")

    ineffective: list[str] = []
    for rule in base_permissions:
        prefix, wildcard = _classify_rule(rule)
        if prefix is None or wildcard is None:
            continue
        if (prefix, wildcard) in prompting_shapes:
            ineffective.append(rule)

    suggestions: list[str] = []
    for prefix, wildcard in sorted(working_shapes):
        suggestions.append(
            f"prefer prefix={prefix} wildcard={wildcard} in plugin-maintenance"
        )

    return Delta(ineffective_rules=ineffective, suggested_rules=suggestions)


def _shapes_for_status(
    *,
    matrix: Matrix,
    status: str,
) -> set[tuple[PathPrefix, WildcardShape]]:
    return {
        (cell.shape.prefix, cell.shape.wildcard)
        for cell in matrix.cells
        if (result := matrix.results.get(cell.cell_id)) and result.status == status
    }


def _classify_rule(rule: str) -> tuple[PathPrefix | None, WildcardShape | None]:
    body = _extract_path(rule)
    if body is None:
        return None, None

    prefix: PathPrefix
    if body.startswith("~/"):
        prefix = "tilde"
    elif body.startswith("/home/"):
        prefix = "home_user"
    elif body.startswith("${HOME}"):
        prefix = "env_home"
    else:
        prefix = "relative"

    if "*/**" in body:
        wildcard: WildcardShape = "star_double_star"
    elif "**" in body:
        wildcard = "double_star"
    elif body.endswith("/*"):
        wildcard = "single_star"
    elif body.endswith("/*/"):
        wildcard = "trailing_slash_star"
    elif "*" in body and not body.endswith("*"):
        wildcard = "mid_path_star"
    elif "*" not in body:
        wildcard = "literal"
    else:
        wildcard = "single_star"

    return prefix, wildcard


def _extract_path(rule: str) -> str | None:
    if "(" not in rule or not rule.endswith(")"):
        return None
    inner = rule.split("(", 1)[1][:-1]
    if ":" in inner:
        inner = inner.split(":", 1)[0]
    return inner
