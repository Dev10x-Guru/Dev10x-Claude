"""`generalize --exclude` keeps named rules exact (GH-1868)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner, Result

from dev10x.commands.permission import generalize

EXCLUDED = "Bash(~/.claude/tools/flux-capacitor-toggle.py on)"
WIDENED = "Bash(/p/foo.sh arg1)"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(json.dumps({"permissions": {"allow": [EXCLUDED, WIDENED]}}))
    monkeypatch.setattr(
        "dev10x.commands.permission._require_settings",
        lambda **_kw: SimpleNamespace(settings_files=[path]),
    )
    monkeypatch.setattr(
        "dev10x.skills.permission.catalog_write._is_git_tracked",
        lambda _path: False,
    )
    return path


@pytest.fixture
def run(settings: Path) -> Result:
    return CliRunner().invoke(generalize, ["--exclude", "flux-capacitor-toggle.py"])


class TestGeneralizeExclude:
    def test_keeps_the_excluded_rule_and_widens_the_rest(
        self,
        run: Result,
        settings: Path,
    ) -> None:
        assert run.exit_code == 0, run.output
        allow = json.loads(settings.read_text())["permissions"]["allow"]
        assert allow == [EXCLUDED, "Bash(/p/foo.sh:*)"]

    def test_lists_the_excluded_rule_as_held(self, run: Result) -> None:
        assert f"HELD (excluded by --exclude 'flux-capacitor-toggle.py'): {EXCLUDED}" in (
            run.output
        )
