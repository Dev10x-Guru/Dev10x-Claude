"""scaffold.sh must create a skill under skills/, not skills/skills/ (GH-1706).

With CLAUDE_PLUGIN_ROOT unset — running from a repo checkout — the
fallback root was two levels above scripts/, which is `skills/`, so the
new skill landed at `skills/skills/<name>/` and the printed next-step
path was wrong the same way.

The script runs from a temp copy of the plugin layout so a test run
never writes a skill into this checkout.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "skills" / "skill-create" / "scripts" / "scaffold.sh"
_TIMEOUT_SECONDS = 30
_NAME = "probe-skill"


@pytest.fixture()
def plugin_copy(tmp_path: Path) -> Path:
    scripts = tmp_path / "skills" / "skill-create" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(_SCRIPT, scripts / "scaffold.sh")
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def scaffold_result(plugin_copy: Path) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PLUGIN_ROOT"}
    return subprocess.run(
        [str(plugin_copy / "skills" / "skill-create" / "scripts" / "scaffold.sh"), _NAME],
        capture_output=True,
        text=True,
        env=env,
        cwd=plugin_copy,
        timeout=_TIMEOUT_SECONDS,
    )


class TestScaffoldWithoutPluginRoot:
    def test_succeeds(self, scaffold_result: subprocess.CompletedProcess[str]) -> None:
        assert scaffold_result.returncode == 0, scaffold_result.stderr

    def test_creates_the_skill_under_skills(
        self,
        plugin_copy: Path,
        scaffold_result: subprocess.CompletedProcess[str],
    ) -> None:
        assert (plugin_copy / "skills" / _NAME / "SKILL.md").is_file()

    def test_does_not_nest_a_second_skills_dir(
        self,
        plugin_copy: Path,
        scaffold_result: subprocess.CompletedProcess[str],
    ) -> None:
        assert not (plugin_copy / "skills" / "skills").exists()

    def test_prints_the_real_skill_index_path(
        self,
        plugin_copy: Path,
        scaffold_result: subprocess.CompletedProcess[str],
    ) -> None:
        expected = plugin_copy / "skills" / "skill-index" / "scripts" / "generate-all.sh"

        assert str(expected) in scaffold_result.stdout
