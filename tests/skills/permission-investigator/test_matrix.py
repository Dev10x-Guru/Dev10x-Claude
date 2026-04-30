"""Tests for the matrix dimension generator and rule renderer (GH-47)."""

from __future__ import annotations

import pytest

from dev10x.skills.permission_investigator.matrix import (
    DEFAULT_LOCATIONS,
    DEFAULT_PREFIXES,
    DEFAULT_TOOLS,
    DEFAULT_WILDCARDS,
    Matrix,
    MatrixResult,
    RuleShape,
    generate_matrix,
)


class TestRuleShapeRender:
    @pytest.fixture
    def fixture_relpath(self) -> str:
        return ".claude/plugins/cache/Test/Plugin/9.9.9/skills/probe/SKILL.md"

    @pytest.fixture
    def home(self) -> str:
        return "/home/janusz"

    def test_tilde_literal_uses_tilde_prefix_and_full_path(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="Read", prefix="tilde", wildcard="literal")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        assert rendered == f"Read(~/{fixture_relpath})"

    def test_home_user_single_star_replaces_filename(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="Read", prefix="home_user", wildcard="single_star")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        expected_dir = (
            "/home/janusz/.claude/plugins/cache/Test/Plugin/9.9.9/skills/probe"
        )
        assert rendered == f"Read({expected_dir}/*)"

    def test_env_home_double_star(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="Read", prefix="env_home", wildcard="double_star")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        assert rendered.startswith("Read(${HOME}/")
        assert rendered.endswith("/**)")

    def test_star_double_star_inserts_double_segment(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="Read", prefix="tilde", wildcard="star_double_star")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        assert "/*/**" in rendered

    def test_mid_path_star_replaces_a_segment(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="Read", prefix="tilde", wildcard="mid_path_star")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        assert "/*/" in rendered

    def test_relative_prefix_emits_no_leading_slash(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="Read", prefix="relative", wildcard="literal")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        assert rendered == f"Read({fixture_relpath})"

    def test_mcp_tool_kind_returns_canonical_mcp_name(
        self,
        fixture_relpath: str,
        home: str,
    ) -> None:
        shape = RuleShape(tool="MCP", prefix="tilde", wildcard="literal")

        rendered = shape.render(fixture_relpath=fixture_relpath, user_home=home)

        assert rendered.startswith("mcp__plugin_Dev10x_cli__")


class TestGenerateMatrix:
    def test_default_matrix_has_full_cartesian_product(self) -> None:
        matrix = generate_matrix()

        expected_count = (
            len(DEFAULT_TOOLS)
            * len(DEFAULT_PREFIXES)
            * len(DEFAULT_WILDCARDS)
            * len(DEFAULT_LOCATIONS)
        )
        assert len(matrix.cells) == expected_count

    def test_cell_ids_are_unique(self) -> None:
        matrix = generate_matrix()

        ids = [cell.cell_id for cell in matrix.cells]

        assert len(ids) == len(set(ids))

    def test_custom_dimensions_shrink_matrix(self) -> None:
        matrix = generate_matrix(
            tools=("Read",),
            prefixes=("tilde",),
            wildcards=("literal", "single_star"),
            locations=("project",),
        )

        assert len(matrix.cells) == 2

    def test_starts_with_no_results(self) -> None:
        matrix = generate_matrix()

        assert matrix.coverage() == (0, len(matrix.cells))


class TestMatrixResultStatus:
    def test_works_when_auto_approved_and_not_prompted(self) -> None:
        result = MatrixResult(
            cell_id="x",
            auto_approved=True,
            prompted=False,
        )

        assert result.status == "works"

    def test_prompts_when_prompted_flag_set(self) -> None:
        result = MatrixResult(
            cell_id="x",
            auto_approved=False,
            prompted=True,
        )

        assert result.status == "prompts"

    def test_error_short_circuits_status(self) -> None:
        result = MatrixResult(
            cell_id="x",
            auto_approved=True,
            prompted=False,
            error="boom",
        )

        assert result.status == "error"


class TestMatrixCoverage:
    def test_reports_results_added(self) -> None:
        matrix = Matrix()
        matrix.cells.append(
            generate_matrix(
                tools=("Read",),
                prefixes=("tilde",),
                wildcards=("literal",),
                locations=("project",),
            ).cells[0]
        )
        matrix.add_result(
            MatrixResult(
                cell_id=matrix.cells[0].cell_id,
                auto_approved=True,
                prompted=False,
            )
        )

        seen, total = matrix.coverage()

        assert seen == 1
        assert total == 1
