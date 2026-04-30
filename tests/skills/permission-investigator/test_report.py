"""Tests for matrix aggregation, markdown report, and delta (GH-47)."""

from __future__ import annotations

import pytest

from dev10x.skills.permission_investigator.matrix import (
    Matrix,
    MatrixCell,
    MatrixResult,
    RuleShape,
)
from dev10x.skills.permission_investigator.report import (
    aggregate_results,
    compute_delta,
    render_markdown_report,
)


def _cell(*, prefix: str, wildcard: str, location: str = "project") -> MatrixCell:
    shape = RuleShape(tool="Read", prefix=prefix, wildcard=wildcard)  # type: ignore[arg-type]
    return MatrixCell(
        shape=shape,
        location=location,  # type: ignore[arg-type]
        cell_id=f"Read.{prefix}.{wildcard}.{location}",
    )


def _result(*, cell_id: str, status: str) -> MatrixResult:
    if status == "works":
        return MatrixResult(cell_id=cell_id, auto_approved=True, prompted=False)
    if status == "prompts":
        return MatrixResult(cell_id=cell_id, auto_approved=False, prompted=True)
    if status == "error":
        return MatrixResult(
            cell_id=cell_id,
            auto_approved=False,
            prompted=False,
            error="boom",
        )
    raise ValueError(f"unknown status {status}")


@pytest.fixture
def populated_matrix() -> Matrix:
    matrix = Matrix()
    cells = [
        _cell(prefix="tilde", wildcard="single_star"),
        _cell(prefix="home_user", wildcard="double_star"),
        _cell(prefix="env_home", wildcard="literal"),
    ]
    for cell in cells:
        matrix.cells.append(cell)
    matrix.add_result(_result(cell_id=cells[0].cell_id, status="works"))
    matrix.add_result(_result(cell_id=cells[1].cell_id, status="prompts"))
    matrix.add_result(_result(cell_id=cells[2].cell_id, status="error"))
    return matrix


class TestAggregateResults:
    def test_groups_results_by_status(self, populated_matrix: Matrix) -> None:
        grouped = aggregate_results(populated_matrix)

        assert len(grouped["works"]) == 1
        assert len(grouped["prompts"]) == 1
        assert len(grouped["error"]) == 1

    def test_ignores_results_without_matching_cell(self) -> None:
        matrix = Matrix()
        matrix.add_result(
            MatrixResult(cell_id="orphan", auto_approved=True, prompted=False)
        )

        grouped = aggregate_results(matrix)

        assert grouped["works"] == []


class TestRenderMarkdownReport:
    def test_includes_outcome_counts_table(self, populated_matrix: Matrix) -> None:
        rendered = render_markdown_report(populated_matrix)

        assert "## Outcome counts" in rendered
        assert "works" in rendered
        assert "prompts" in rendered

    def test_lists_each_cell(self, populated_matrix: Matrix) -> None:
        rendered = render_markdown_report(populated_matrix)

        for cell in populated_matrix.cells:
            assert cell.cell_id in rendered

    def test_marks_unrun_cells_as_not_run(self) -> None:
        matrix = Matrix()
        matrix.cells.append(_cell(prefix="tilde", wildcard="literal"))

        rendered = render_markdown_report(matrix)

        assert "(not run)" in rendered


class TestComputeDelta:
    def test_flags_rules_whose_shape_matched_a_prompting_cell(self) -> None:
        matrix = Matrix()
        cell = _cell(prefix="home_user", wildcard="star_double_star")
        matrix.cells.append(cell)
        matrix.add_result(_result(cell_id=cell.cell_id, status="prompts"))

        delta = compute_delta(
            matrix=matrix,
            base_permissions=[
                "Read(/home/janusz/.claude/plugins/cache/Dev10x-Guru/Dev10x/*/**)",
                "Bash(git log:*)",
            ],
        )

        assert any(
            "*/**" in rule for rule in delta.ineffective_rules
        ), "Expected the */** rule to be flagged"
        assert all(
            "git log" not in rule for rule in delta.ineffective_rules
        ), "Bash rules should not be flagged by Read prompts"

    def test_no_rules_flagged_when_all_cells_work(self) -> None:
        matrix = Matrix()
        cell = _cell(prefix="tilde", wildcard="single_star")
        matrix.cells.append(cell)
        matrix.add_result(_result(cell_id=cell.cell_id, status="works"))

        delta = compute_delta(
            matrix=matrix,
            base_permissions=["Read(~/.claude/plugins/cache/Test/Plugin/9.9.9/x/*)"],
        )

        assert delta.ineffective_rules == []
        assert any("single_star" in line for line in delta.suggested_rules)

    def test_skips_rules_outside_recognised_shape(self) -> None:
        matrix = Matrix()
        cell = _cell(prefix="tilde", wildcard="literal")
        matrix.cells.append(cell)
        matrix.add_result(_result(cell_id=cell.cell_id, status="prompts"))

        delta = compute_delta(
            matrix=matrix,
            base_permissions=["mcp__plugin_Dev10x_cli__detect_tracker"],
        )

        assert delta.ineffective_rules == []
