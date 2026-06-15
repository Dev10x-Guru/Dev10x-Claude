"""Tests for dev10x.skills.permission_investigator.runner (GH-525).

The investigate CLI command bodies delegate their file read/mutate/write
logic to these domain functions. The CLI suite
(tests/commands/test_permission_investigate.py) exercises them end-to-end;
this module pins the apply-cell target branches that a single CLI cell
cannot reach on its own (project vs global location).
"""

from __future__ import annotations

import json
from pathlib import Path

from dev10x.skills.permission_investigator import runner


def _prepare(tmp_path: Path) -> tuple[Path, Path]:
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    workdir = tmp_path / "wd"
    runner.prepare(workdir=workdir, user_home=fake_home, default_workdir=workdir)
    return workdir / "matrix.json", fake_home


class TestApplyCell:
    def test_applies_every_cell_across_project_and_global_targets(
        self,
        tmp_path: Path,
    ) -> None:
        state_path, fake_home = _prepare(tmp_path)
        state = json.loads(state_path.read_text())

        locations_seen: set[str] = set()
        for cell in state["cells"]:
            result = runner.apply_cell(
                state_path=state_path,
                cell_id=cell["cell_id"],
                user_home=fake_home,
            )
            assert result["exit_code"] == 0
            assert any(msg.startswith("Applied rule:") for msg in result["messages"])
            locations_seen.add(cell["location"])

        # The matrix must exercise both target branches for full coverage.
        assert any(loc in ("project", "both") for loc in locations_seen)
        assert any(loc in ("global", "both") for loc in locations_seen)

    def test_errors_on_unknown_cell(self, tmp_path: Path) -> None:
        state_path, fake_home = _prepare(tmp_path)

        result = runner.apply_cell(
            state_path=state_path,
            cell_id="no-such-cell",
            user_home=fake_home,
        )

        assert result["exit_code"] == 1
        assert "unknown cell_id" in result["errors"][0]
