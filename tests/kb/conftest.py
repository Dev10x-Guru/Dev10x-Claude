from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dev10x.core.domain.common.result import SuccessResult
from dev10x.core.domain.knowledge_vault import VaultConfig
from dev10x.kb.config import KbConfig
from dev10x.kb.record import SourceKind, SourceRecord, write_record

Completed = Callable[..., subprocess.CompletedProcess[str]]


@pytest.fixture
def completed() -> Completed:
    def build(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return build


@pytest.fixture
def tools_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")


@pytest.fixture
def timeout_run() -> Callable[..., Any]:
    def run(args: list[str], **_: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    return run


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    path.mkdir()
    return path


@pytest.fixture
def records(tmp_path: Path) -> Path:
    return tmp_path / "work"


@pytest.fixture
def kb_config(vault: Path) -> KbConfig:
    return KbConfig(
        vault=VaultConfig(source="test", configured=True, vault=vault),
        hub=vault / "Sources" / "Harvested.md",
    )


@pytest.fixture
def youtube_record(records: Path) -> SourceRecord:
    record = SourceRecord(
        id="yt-vid1",
        kind=SourceKind.YOUTUBE,
        url="https://www.youtube.com/watch?v=vid1",
        title="Talk",
        author="Channel",
        published="20261107",
        description="About",
        transcript="spoken",
        metrics={"views": "12000", "likes": "600", "channel_subs": "5000"},
        measured_at="2026-11-17",
    )
    assert isinstance(write_record(record=record, directory=records), SuccessResult)
    return record
