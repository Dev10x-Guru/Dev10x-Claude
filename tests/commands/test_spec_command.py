from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.spec import spec


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    return root


def test_drift_clean_spec_exits_zero(project_root: Path) -> None:
    code_file = project_root / "src" / "widget.py"
    code_file.write_text("def build_widget():\n    return 1\n")
    spec_path = project_root / "spec.md"
    spec_path.write_text(
        "## Architecture\n"
        "`src/widget.py`\n"
        "## Acceptance Criteria\n"
        "`build_widget(...)` returns a widget.\n"
    )

    result = CliRunner().invoke(
        spec,
        ["drift", str(spec_path), "--project-root", str(project_root)],
    )

    assert result.exit_code == 0
    assert "No drift detected" in result.output


def test_drift_missing_file_reference_exits_one(project_root: Path) -> None:
    spec_path = project_root / "spec.md"
    spec_path.write_text("## Architecture\n`src/missing.py`\n")

    result = CliRunner().invoke(
        spec,
        ["drift", str(spec_path), "--project-root", str(project_root)],
    )

    assert result.exit_code == 1
    assert "structural" in result.output
    assert "src/missing.py" in result.output


def test_drift_missing_spec_exits_two(project_root: Path) -> None:
    spec_path = project_root / "does-not-exist.md"

    result = CliRunner().invoke(
        spec,
        ["drift", str(spec_path), "--project-root", str(project_root)],
    )

    assert result.exit_code == 2
    assert "behavioural" in result.output
    assert "spec file missing" in result.output
