"""`dev10x skill kb` commands print one JSON object each (GH-1985)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from dev10x.commands.skill import skill
from dev10x.core.domain.common.result import err, ok
from dev10x.core.domain.dev10x_paths import Dev10xConfigDir
from dev10x.core.session import repo_address
from dev10x.kb import persist as persist_module
from dev10x.kb import record as record_module
from dev10x.kb.record import SourceRecord


class _FakeFiles:
    def to_dict(self) -> dict[str, str]:
        return {"id": "yt-a"}


@pytest.fixture
def configured(
    vault: Path, records: Path, monkeypatch: pytest.MonkeyPatch, youtube_record: SourceRecord
) -> Path:
    config = Dev10xConfigDir.knowledge_vault_yaml()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f"vault: {vault}\nkb:\n  hub: Hub.md\n  transcribe_model: tiny\n")
    monkeypatch.setattr(repo_address, "resolve_name_with_owner", lambda: ok("org/repo"))
    monkeypatch.setattr(record_module, "workdir", lambda: records)
    monkeypatch.setattr(persist_module, "workdir", lambda: records)
    return vault


@pytest.fixture
def fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake fetch_source: one link succeeds, one fails; records the model used."""
    models: list[str] = []
    outcomes = {"https://youtu.be/a": ok(_FakeFiles()), "https://bad": err("unsupported")}

    def fake(*, url: str, model: str, **_: Any) -> Any:
        models.append(model)
        return outcomes[url]

    monkeypatch.setattr("dev10x.kb.fetch_source", fake)
    return models


def _invoke(*args: str) -> tuple[Result, Any]:
    result = CliRunner().invoke(skill, ["kb", *args])
    return result, json.loads(result.output)


def test_config_reports_places_and_tools(configured: Path) -> None:
    result, payload = _invoke("config")

    assert result.exit_code == 0
    assert (payload["hub"], payload["transcribe_model"]) == (str(configured / "Hub.md"), "tiny")
    assert "yt-dlp" in payload["tools"]


def test_config_without_repo_still_resolves(
    configured: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repo_address, "resolve_name_with_owner", lambda: err("no origin"))

    result, payload = _invoke("config")

    assert result.exit_code == 0
    assert payload["configured"] is True


def test_config_error_is_json_on_stdout(configured: Path) -> None:
    Dev10xConfigDir.knowledge_vault_yaml().write_text("vault: /does/not/exist\n")

    result, payload = _invoke("config")

    assert result.exit_code == 1
    assert "does not exist or is not a directory" in payload["error"]


def test_fetch_reports_records_and_errors(configured: Path, fetched: list[str]) -> None:
    result, payload = _invoke("fetch", "https://youtu.be/a", "https://bad")

    assert result.exit_code == 0
    assert payload["records"] == [{"url": "https://youtu.be/a", "id": "yt-a"}]
    assert payload["errors"] == [{"url": "https://bad", "error": "unsupported"}]
    assert fetched == ["tiny", "tiny"]


def test_fetch_fails_when_nothing_was_fetched(configured: Path, fetched: list[str]) -> None:
    result, payload = _invoke("fetch", "--model", "base", "https://bad")

    assert result.exit_code == 1
    assert payload["records"] == []
    assert fetched == ["base"]


def test_persist_writes_into_the_vault(configured: Path) -> None:
    result, payload = _invoke(
        "persist", "--id", "yt-vid1", "--dest", str(configured / "Att"), "--name", "J - T"
    )

    assert result.exit_code == 0
    assert Path(payload["text"]).read_text() == "spoken\n"


def test_persist_error_exits_non_zero(configured: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"

    result, payload = _invoke("persist", "--id", "yt-vid1", "--dest", str(outside), "--name", "J")

    assert result.exit_code == 1
    assert "is outside the vault" in payload["error"]


def test_index_writes_the_hub(configured: Path) -> None:
    note = configured / "day.md"
    note.write_text("x")

    result, payload = _invoke(
        "index", "--id", "yt-vid1", "--name", "J - T", "--structure", "a->b", "--note", str(note)
    )

    assert result.exit_code == 0
    assert payload["action"] == "created"


def test_index_error_exits_non_zero(configured: Path) -> None:
    note = configured / "day.md"

    result, payload = _invoke(
        "index", "--id", "yt-none", "--name", "J", "--structure", "s", "--note", str(note)
    )

    assert result.exit_code == 1
    assert "run `dev10x skill kb fetch` first" in payload["error"]


def test_link_prints_encoded_link() -> None:
    result, payload = _invoke("link", "/v/a.md", "/v/b c.md", "B")

    assert result.exit_code == 0
    assert payload == {"link": "[B](b%20c.md)"}
