"""Tests for `dev10x skill reflect` (GH-1822)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from dev10x.domain.common.result import err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.commands.skill import reflect
from dev10x.core.session import repo_address


@pytest.fixture(autouse=True)
def _repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_address, "resolve_name_with_owner", lambda **_: ok("acme/shop"))


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    (path / "Retros").mkdir(parents=True)
    config = Dev10xConfigDir.knowledge_vault_yaml()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"vault: {path}\n", encoding="utf-8")
    return path


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(reflect, list(args))


def _payload(result: Result) -> dict:
    return json.loads(result.output)


class TestConfig:
    def test_unconfigured_reports_reason_and_succeeds(self) -> None:
        result = _invoke("config")

        assert result.exit_code == 0
        assert _payload(result)["configured"] is False

    @pytest.mark.usefixtures("vault")
    def test_configured_reports_repo(self) -> None:
        result = _invoke("config")

        assert result.exit_code == 0
        assert _payload(result)["repo"] == "acme/shop"

    @pytest.mark.usefixtures("vault")
    def test_no_origin_still_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(repo_address, "resolve_name_with_owner", lambda **_: err("no origin"))

        result = _invoke("config")

        assert _payload(result)["repo"] is None

    def test_malformed_config_fails_as_json(self) -> None:
        config = Dev10xConfigDir.knowledge_vault_yaml()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("vault: relative\n", encoding="utf-8")

        result = _invoke("config")

        assert result.exit_code == 1
        assert "must be absolute" in _payload(result)["error"]


class TestIndexAdd:
    def test_writes_line(self, vault: Path) -> None:
        result = _invoke("index-add", "--folder", "Retros", "--line", "- [[A]]")

        assert result.exit_code == 0
        assert _payload(result)["action"] == "created"
        assert "- [[A]]" in (vault / "Retros" / "index.md").read_text()

    def test_unconfigured_fails(self) -> None:
        result = _invoke("index-add", "--folder", "Retros", "--line", "- [[A]]")

        assert result.exit_code == 1
        assert "no knowledge vault" in _payload(result)["error"]

    @pytest.mark.usefixtures("vault")
    def test_escape_fails(self) -> None:
        result = _invoke("index-add", "--folder", "../x", "--line", "- [[A]]")

        assert result.exit_code == 1


class TestLogAdd:
    def test_writes_dated_entry(self, vault: Path) -> None:
        result = _invoke(
            "log-add", "--folder", "Retros", "--entry", "x", "--date", "2026-11-05", "--create"
        )

        assert _payload(result)["action"] == "created"
        assert "## 2026-11-05" in (vault / "Retros" / "log.md").read_text()

    @pytest.fixture
    def undated_run(self, vault: Path) -> tuple[Result, set[str], str]:
        before = date.today().isoformat()
        result = _invoke("log-add", "--folder", "Retros", "--entry", "x", "--create")
        after = date.today().isoformat()
        return result, {before, after}, (vault / "Retros" / "log.md").read_text()

    def test_defaults_to_today(self, undated_run: tuple[Result, set[str], str]) -> None:
        result, run_days, text = undated_run

        assert result.exit_code == 0
        assert any(f"## {day}\n" in text for day in run_days)

    @pytest.mark.usefixtures("vault")
    def test_skips_without_log(self) -> None:
        result = _invoke("log-add", "--folder", "Retros", "--entry", "x")

        assert result.exit_code == 0
        assert _payload(result)["action"] == "skipped"

    def test_unconfigured_fails(self) -> None:
        result = _invoke("log-add", "--folder", "Retros", "--entry", "x")

        assert result.exit_code == 1

    @pytest.mark.usefixtures("vault")
    def test_empty_entry_fails(self) -> None:
        result = _invoke("log-add", "--folder", "Retros", "--entry", " ")

        assert result.exit_code == 1
