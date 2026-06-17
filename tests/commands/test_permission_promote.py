"""Tests for `dev10x permission promote-plan [--apply]` (GH-470 / GH-480)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.permission import promote_plan
from dev10x.domain.common.result import ok

READ_TOOL = "mcp__claude_ai_Slack__slack_read_channel"
DOMAIN_RULE = "WebFetch(domain:arxiv.org)"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Wire promote-plan to a tmp global file + a tmp project settings file.

    Returns the global settings path so tests can assert on writes.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    global_settings = home / ".claude" / "settings.json"
    global_settings.write_text(json.dumps({"permissions": {"allow": []}}))

    project = tmp_path / "proj" / ".claude" / "settings.local.json"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps({"permissions": {"allow": [READ_TOOL, DOMAIN_RULE]}}))

    from dev10x.skills.permission import update_paths as paths_mod

    monkeypatch.setattr(paths_mod, "find_config", lambda: ok(tmp_path / "config.yaml"))
    monkeypatch.setattr(paths_mod, "load_config", lambda _path: {"roots": []})
    monkeypatch.setattr(paths_mod, "find_settings_files", lambda **_kw: [project])
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return global_settings


def test_dry_run_plan_is_default(env: Path) -> None:
    result = CliRunner().invoke(promote_plan, ["--quiet"])
    assert result.exit_code == 0
    assert "DRY RUN — no files modified" in result.output
    assert json.loads(env.read_text())["permissions"]["allow"] == []


def test_apply_writes_to_global(env: Path) -> None:
    result = CliRunner().invoke(promote_plan, ["--apply", "--quiet"])
    assert result.exit_code == 0
    assert "applied to global settings" in result.output
    allow = json.loads(env.read_text())["permissions"]["allow"]
    assert READ_TOOL in allow
    assert DOMAIN_RULE in allow


def test_apply_dry_run_previews_without_writing(env: Path) -> None:
    result = CliRunner().invoke(promote_plan, ["--apply", "--dry-run", "--quiet"])
    assert result.exit_code == 0
    assert "DRY RUN — no files modified" in result.output
    assert json.loads(env.read_text())["permissions"]["allow"] == []


def test_config_line_printed_without_quiet(env: Path) -> None:
    result = CliRunner().invoke(promote_plan, [])
    assert result.exit_code == 0
    assert "Config:" in result.output


def test_proactive_dry_run_lists_curated_surface(env: Path) -> None:
    # --proactive ignores project settings and reads the shipped catalog.
    result = CliRunner().invoke(promote_plan, ["--proactive", "--quiet"])
    assert result.exit_code == 0
    assert "DRY RUN — no files modified" in result.output
    assert "mcp__claude_ai_Sentry__search_issues" in result.output
    assert json.loads(env.read_text())["permissions"]["allow"] == []


def test_proactive_apply_seeds_default_safe_not_pii(env: Path) -> None:
    result = CliRunner().invoke(promote_plan, ["--proactive", "--apply", "--quiet"])
    assert result.exit_code == 0
    allow = json.loads(env.read_text())["permissions"]["allow"]
    assert "mcp__claude_ai_Sentry__search_issues" in allow
    assert "mcp__claude_ai_Atlassian__getJiraIssue" in allow
    # PII/secret opt-in groups are never proactively seeded.
    assert "mcp__claude_ai_Google_Drive__read_file_content" not in allow
