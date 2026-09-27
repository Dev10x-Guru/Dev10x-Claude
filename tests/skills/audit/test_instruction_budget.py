"""Tests for instruction-budget analysis (GH-882)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.audit import instruction_budget as mod


class TestIsActionable:
    """Classifies single lines as actionable or not."""

    @pytest.mark.parametrize(
        "line",
        [
            "1. Create a task for the work",
            "2. **REQUIRED:** Call AskUserQuestion",
            "**REQUIRED: Call `AskUserQuestion`**",
            "- Fetch the ticket before branching",
            "TaskCreate(subject='x')",
            "AskUserQuestion(questions=[...])",
            "**MUST delegate to dev10x:git-commit**",
            "**DO NOT skip verification**",
        ],
    )
    def test_classifies_as_actionable(self, line: str) -> None:
        assert mod.is_actionable(line) is True

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "# Heading",
            "## Subsection",
            "This is a prose paragraph.",
            "| cell1 | cell2 |",
            "> quoted text",
            "- the pattern matches when imperatives appear",
            "name: dev10x:git-commit",
        ],
    )
    def test_classifies_as_inactive(self, line: str) -> None:
        assert mod.is_actionable(line) is False


class TestCountInstructions:
    """Counts actionable instructions in a skill file."""

    @pytest.fixture
    def small_skill(self, tmp_path: Path) -> Path:
        path = tmp_path / "small.md"
        path.write_text(
            "---\n"
            "name: dev10x:tiny\n"
            "---\n"
            "# Overview\n"
            "\n"
            "Prose about the skill.\n"
            "\n"
            "## Workflow\n"
            "\n"
            "1. Create the task\n"
            "2. Run the command\n"
            "3. Report results\n"
            "\n"
            "**REQUIRED:** invoke the helper\n"
        )
        return path

    @pytest.fixture
    def large_skill(self, tmp_path: Path) -> Path:
        path = tmp_path / "large.md"
        body = ["# Big skill\n", "Prose paragraph.\n", "\n"]
        body.extend([f"{i}. Do step {i}\n" for i in range(1, 160)])
        path.write_text("".join(body))
        return path

    def test_counts_ordered_list_and_enforcement_markers(self, small_skill: Path) -> None:
        report = mod.count_instructions(small_skill)
        assert report.count == 4

    def test_excludes_frontmatter(self, small_skill: Path) -> None:
        report = mod.count_instructions(small_skill)
        assert "dev10x:tiny" not in str(report.count)

    def test_status_ok_under_warn(self, small_skill: Path) -> None:
        report = mod.count_instructions(small_skill, warn=10, over=20)
        assert report.status == "ok"

    def test_status_warn_at_threshold(self, small_skill: Path) -> None:
        report = mod.count_instructions(small_skill, warn=4, over=20)
        assert report.status == "warn"

    def test_status_over_threshold(self, large_skill: Path) -> None:
        report = mod.count_instructions(large_skill, warn=50, over=100)
        assert report.status == "over"
        assert report.count >= 150


class TestCodeBlockExclusion:
    """Lines inside fenced code blocks are NOT counted."""

    def test_fenced_code_lines_excluded(self, tmp_path: Path) -> None:
        path = tmp_path / "code.md"
        path.write_text(
            "# Example\n"
            "\n"
            "```\n"
            "1. fake instruction in code\n"
            "2. another fake\n"
            "3. still fake\n"
            "```\n"
            "\n"
            "1. Real instruction\n"
        )
        report = mod.count_instructions(path)
        assert report.count == 1


class TestScan:
    """Scans multiple files and returns per-file reports."""

    def test_returns_report_per_file(self, tmp_path: Path) -> None:
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("1. first\n")
        b.write_text("1. first\n2. second\n3. third\n")

        reports = mod.scan([a, b])
        assert len(reports) == 2
        assert reports[0].count == 1
        assert reports[1].count == 3

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.md"
        reports = mod.scan([missing])
        assert reports == []


class TestFindSkillFiles:
    """Finds SKILL.md files under a directory."""

    def test_finds_skill_md_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "skill-a").mkdir()
        (tmp_path / "skill-a" / "SKILL.md").write_text("")
        (tmp_path / "skill-b" / "nested").mkdir(parents=True)
        (tmp_path / "skill-b" / "nested" / "SKILL.md").write_text("")
        (tmp_path / "skill-b" / "other.md").write_text("")

        files = mod.find_skill_files(tmp_path)
        assert len(files) == 2
        assert all(f.name == "SKILL.md" for f in files)
