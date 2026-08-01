"""CLI surface of the GH-937 dependency staleness sweep.

Every test patches the fetcher — `dev10x deps sweep` never reaches PyPI
under pytest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dev10x.commands.deps import deps
from dev10x.domain.common.result import err, ok


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["click>=8.0,<9"]\n')
    return tmp_path


def stub_latest(version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dev10x.dependency_sweep.fetch_latest_version",
        lambda distribution, timeout=None: ok(version),
    )


def test_sweep_exits_zero_when_no_pin_is_stale(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_latest("8.1.7", monkeypatch)

    result = CliRunner().invoke(deps, ["sweep", "--root", str(repo)])

    assert result.exit_code == 0
    assert "No pinned dependency" in result.output


def test_sweep_exits_one_when_a_pin_is_stale(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_latest("9.0.1", monkeypatch)

    result = CliRunner().invoke(deps, ["sweep", "--root", str(repo)])

    assert result.exit_code == 1
    assert "**click**" in result.output


def test_sweep_can_report_a_stale_pin_without_failing(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_latest("9.0.1", monkeypatch)

    result = CliRunner().invoke(deps, ["sweep", "--root", str(repo), "--no-fail-on-stale"])

    assert result.exit_code == 0


def test_sweep_emits_json(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_latest("9.0.1", monkeypatch)

    result = CliRunner().invoke(
        deps,
        ["sweep", "--root", str(repo), "--json", "--no-fail-on-stale", "--timeout", "3"],
    )

    payload = json.loads(result.output)
    assert payload["stale"][0]["distribution"] == "click"
    assert payload["pins"] == 1


def test_sweep_defaults_to_the_effective_working_directory(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_latest("8.1.7", monkeypatch)
    monkeypatch.setattr("dev10x.subprocess_utils.effective_cwd", lambda: str(repo))

    result = CliRunner().invoke(deps, ["sweep"])

    assert result.exit_code == 0
    assert "Checked 1 pinned requirement(s)" in result.output


def test_sweep_reports_a_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dev10x.subprocess_utils.effective_cwd", lambda: None)
    monkeypatch.setattr("dev10x.dependency_sweep.sweep", lambda root, fetch: err("boom"))

    result = CliRunner().invoke(deps, ["sweep"])

    assert result.exit_code == 1
    assert "boom" in result.output
