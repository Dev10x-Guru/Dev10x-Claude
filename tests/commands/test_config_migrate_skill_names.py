"""`dev10x config migrate-skill-names` CLI (ADR-0034 Stage A4, GH-1559)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from dev10x.cli import cli
from dev10x.core.domain.common.result import Result, err, ok
from dev10x.core.skills.upgrade_cleanup import skill_names
from dev10x.core.skills.upgrade_cleanup.skill_names import ConfigRewrite


def _stub(monkeypatch: pytest.MonkeyPatch, *, result: Result[list[ConfigRewrite]]) -> None:
    def fake(**kwargs: Any) -> Result[list[ConfigRewrite]]:
        return result

    monkeypatch.setattr(skill_names, "migrate_user_configs", fake)


class TestMigrateSkillNames:
    def test_shipped_table_has_nothing_to_migrate(self) -> None:
        result = CliRunner().invoke(cli, ["config", "migrate-skill-names"])

        assert (result.exit_code, result.output) == (
            0,
            "Dev10x config: no renamed skill names to migrate.\n",
        )

    @pytest.mark.parametrize(
        ("args", "verb"),
        [([], "Rewrote"), (["--dry-run"], "Would rewrite")],
    )
    def test_reports_each_rewritten_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        args: list[str],
        verb: str,
    ) -> None:
        path = tmp_path / "friction.yaml"
        _stub(monkeypatch, result=ok([ConfigRewrite(path=path, replacements=2)]))

        result = CliRunner().invoke(cli, ["config", "migrate-skill-names", *args])

        assert result.output == f"{verb} 2 skill name(s) in {path}\n"

    def test_domain_error_exits_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, result=err("lock held. Please try again."))

        result = CliRunner().invoke(cli, ["config", "migrate-skill-names"])

        assert (result.exit_code, "lock held" in result.output) == (1, True)
