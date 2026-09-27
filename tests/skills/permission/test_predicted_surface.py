"""Predicting the prompt surface from settings (GH-1408).

Tier 1 (GH-1406) can only count denials. The ask-rule and no-match paths
prompt without reaching a hook, so this tier predicts them from the
catalog and the settings file — and must say it is a prediction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.permission import report as report_cmd
from dev10x.domain.common.result import ok
from dev10x.permission.service import PermissionContext
from dev10x.skills.permission.friction_report import (
    PredictedSurface,
    format_predicted_surface,
    predict_surface,
    predict_surfaces,
)

CATALOG_ALLOW = ["Bash(git status:*)", "Bash(gh pr view:*)", "mcp__plugin_dev10x_cli__pr_get"]
CATALOG_ASK = ["Bash(gh api -X DELETE:*)"]


def _settings(tmp_path: Path, *, allow=(), deny=(), ask=()) -> Path:
    path = tmp_path / "settings.local.json"
    path.write_text(
        json.dumps({"permissions": {"allow": list(allow), "deny": list(deny), "ask": list(ask)}})
    )
    return path


@pytest.fixture
def surface(tmp_path: Path) -> PredictedSurface:
    path = _settings(
        tmp_path,
        allow=["Bash(git status:*)"],
        deny=["Bash(gh pr view:*)"],
        ask=["Bash(gh api -X DELETE:*)", "Bash(rm:*)"],
    )
    return predict_surface(path=path, base_permissions=CATALOG_ALLOW, base_asks=CATALOG_ASK)


class TestPredictSurface:
    def test_no_match_is_catalog_allow_the_file_neither_allows_nor_denies(
        self, surface: PredictedSurface
    ) -> None:
        assert surface.no_match == ["mcp__plugin_dev10x_cli__pr_get"]

    def test_ask_rules_are_keyed_by_provenance(self, surface: PredictedSurface) -> None:
        assert surface.ask == {
            "default": ["Bash(gh api -X DELETE:*)"],
            "project": ["Bash(rm:*)"],
        }

    def test_total_counts_both_paths(self, surface: PredictedSurface) -> None:
        assert surface.total == 3

    def test_unreadable_file_is_flagged_not_reported_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not json")

        surface = predict_surface(path=path, base_permissions=CATALOG_ALLOW, base_asks=[])

        assert surface.unreadable is not None
        assert surface.total == 0


class TestFormatPredictedSurface:
    def test_labels_itself_a_prediction(self, surface: PredictedSurface) -> None:
        text = "\n".join(format_predicted_surface([surface]))

        assert "what WOULD prompt, not what did" in text
        assert "Prediction, not evidence." in text

    def test_reports_per_file_counts_with_ask_origins(self, surface: PredictedSurface) -> None:
        lines = format_predicted_surface([surface])

        assert "  1 no-match / 2 ask (1 default, 1 project)" in lines

    def test_ranks_by_rule_family(self, surface: PredictedSurface) -> None:
        lines = format_predicted_surface([surface])

        assert "By rule family:" in lines
        assert "      1  ( 33.3%)  mcp" in lines

    def test_warns_on_an_unreadable_file(self, tmp_path: Path) -> None:
        unreadable = PredictedSurface(path=tmp_path / "x.json", unreadable="invalid JSON: boom")

        lines = format_predicted_surface([unreadable])

        assert "  WARNING: invalid JSON: boom — could not predict" in lines
        assert "By rule family:" not in lines


class TestPredictSurfaces:
    def test_renders_the_catalog_once_for_every_file(self, tmp_path: Path) -> None:
        path = _settings(tmp_path, allow=["Bash(git status:*)"])

        surfaces = predict_surfaces(
            config={"base_permissions": ["Bash(git status:*)", "Bash(git log:*)"]},
            settings_files=[path],
        )

        assert [s.no_match for s in surfaces] == [["Bash(git log:*)"]]


class TestReportCommand:
    @pytest.fixture
    def context(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PermissionContext:
        ctx = PermissionContext(
            config_path=tmp_path / "config.yaml",
            config={"base_permissions": ["Bash(git log:*)"]},
            settings_files=[_settings(tmp_path)],
        )
        monkeypatch.setattr(
            "dev10x.commands.permission.load_permission_context",
            lambda **_kw: ok(ctx),
        )
        return ctx

    def test_predicted_flag_prints_the_prediction(self, context: PermissionContext) -> None:
        result = CliRunner().invoke(report_cmd, ["--predicted"])

        assert result.exit_code == 0
        assert "1 no-match / 0 ask" in result.output

    def test_predicted_flag_without_settings_files_says_so(
        self, context: PermissionContext
    ) -> None:
        context.settings_files.clear()

        result = CliRunner().invoke(report_cmd, ["--predicted"])

        assert result.exit_code == 0
        assert "No settings files found." in result.output
