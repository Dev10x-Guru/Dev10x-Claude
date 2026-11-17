"""The `kb:` section of knowledge-vault.yaml (GH-1985)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.core.domain.common.config_io import ConfigIOError
from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.kb import config as config_module
from dev10x.kb.config import KbConfig, resolve_kb_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "knowledge-vault.yaml"
    path.write_text(body)
    return path


def _resolve(path: Path) -> object:
    return resolve_kb_config(repo="org/repo", path=path)


def test_missing_file_is_unconfigured(tmp_path: Path) -> None:
    result = _resolve(tmp_path / "absent.yaml")

    assert isinstance(result, SuccessResult)
    assert (result.value.configured, result.value.hub) == (False, None)


def test_vault_without_kb_section_keeps_steps_off(tmp_path: Path, vault: Path) -> None:
    result = _resolve(_write(tmp_path, f"vault: {vault}\n"))

    assert isinstance(result, SuccessResult)
    assert result.value.to_dict() == {
        "configured": True,
        "reason": "",
        "source": str(tmp_path / "knowledge-vault.yaml"),
        "vault": str(vault),
        "rules_note": None,
        "hub": None,
        "topics": None,
        "people": None,
        "strategy_hub": None,
        "transcribe_model": "small",
    }


def test_resolves_every_place_inside_the_vault(tmp_path: Path, vault: Path) -> None:
    body = (
        f"vault: {vault}\n"
        "kb:\n"
        "  hub: Sources/Harvested.md\n"
        "  topics: Sources/Topics/\n"
        "  people: People\n"
        "  strategy_hub: Projects/Strategy.md\n"
        "  transcribe_model: ' medium '\n"
    )

    result = _resolve(_write(tmp_path, body))

    assert isinstance(result, SuccessResult)
    config: KbConfig = result.value
    assert (config.hub, config.topics, config.people, config.strategy_hub) == (
        vault / "Sources/Harvested.md",
        vault / "Sources/Topics",
        vault / "People",
        vault / "Projects/Strategy.md",
    )
    assert config.transcribe_model == "medium"


@pytest.mark.parametrize(
    ("kb", "message"),
    [
        ("kb: [1]", "`kb:` must be a mapping"),
        ("kb:\n  hub: ''", "non-empty"),
        ("kb:\n  hub: Sources", "Markdown note"),
        ("kb:\n  people: ../outside", "must not contain '..'"),
        ("kb:\n  transcribe_model: 3", "whisper model"),
    ],
)
def test_rejects_bad_places(kb: str, message: str, tmp_path: Path, vault: Path) -> None:
    result = _resolve(_write(tmp_path, f"vault: {vault}\n{kb}\n"))

    assert isinstance(result, ErrorResult)
    assert message in result.error


def test_propagates_broken_vault_config(tmp_path: Path) -> None:
    result = _resolve(_write(tmp_path, "vault: [unclosed\n"))

    assert isinstance(result, ErrorResult)
    assert result.details["source"] == str(tmp_path / "knowledge-vault.yaml")


def test_section_reports_unreadable_file(
    tmp_path: Path, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, f"vault: {vault}\n")

    def broken(*_: object, **__: object) -> None:
        raise ConfigIOError("boom")

    monkeypatch.setattr(config_module, "load_yaml", broken)

    result = _resolve(path)

    assert isinstance(result, ErrorResult)
    assert "boom" in result.error
