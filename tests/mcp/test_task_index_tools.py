"""Task-index MCP boundary — wire shape of the park family's store (GH-1009).

The domain behaviour is covered in `tests/session/test_task_index.py`; these
assert the `to_wire()` contract callers actually branch on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from dev10x.mcp.task_index_tools import task_index_append, task_index_get, task_index_set
from dev10x.session import preset_pin


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    main = tmp_path / "work" / "Dev10x-Claude"
    (main / ".git").mkdir(parents=True)
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(main / ".git"))
    return main


@pytest.fixture
def stored(repo: Path) -> Any:
    from dev10x.domain.dev10x_paths import Dev10xConfigDir

    def read() -> dict[str, Any]:
        path = Dev10xConfigDir.task_index_yaml(repo_name="Dev10x-Claude")
        return yaml.safe_load(path.read_text()) or {}

    return read


@pytest.fixture
def no_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)


@pytest.mark.asyncio
async def test_get_returns_the_documented_success_keys(repo: Path) -> None:
    wire = await task_index_get(cwd=str(repo))

    assert set(wire) == {
        "path",
        "repo_name",
        "exists",
        "legacy_read",
        "legacy_path",
        "tasks",
        "continuation_prompt",
        "insights",
        "branch",
        "tickets",
        "wrapped_at",
    }
    assert "error" not in wire


@pytest.mark.asyncio
async def test_append_then_get_round_trips(repo: Path) -> None:
    await task_index_append(entry={"subject": "Wire retries", "source": "park"}, cwd=str(repo))

    wire = await task_index_get(cwd=str(repo))

    assert wire["tasks"] == [{"subject": "Wire retries", "source": "park"}]


@pytest.mark.asyncio
async def test_append_reports_the_task_count(repo: Path) -> None:
    wire = await task_index_append(
        entry={"subject": "Wire retries", "source": "park"}, cwd=str(repo)
    )

    assert wire["task_count"] == 1
    assert "error" not in wire


@pytest.mark.asyncio
async def test_set_writes_wrap_up_state(repo: Path, stored: Any) -> None:
    wire = await task_index_set(
        continuation_prompt="Resume the retry work",
        tickets=["GH-1009"],
        cwd=str(repo),
    )

    assert wire["updated_keys"] == ["continuation_prompt", "tickets"]
    assert stored()["continuation_prompt"] == "Resume the retry work"


@pytest.mark.asyncio
async def test_append_surfaces_a_validation_error_on_the_wire(repo: Path) -> None:
    wire = await task_index_append(entry={"subject": "No source"}, cwd=str(repo))

    assert "source" in wire["error"]


@pytest.mark.asyncio
async def test_get_surfaces_a_repo_error_on_the_wire(no_repo: None) -> None:
    wire = await task_index_get(cwd="/tmp")

    assert wire["error"] == "Not in a git repository"


@pytest.mark.asyncio
async def test_set_surfaces_a_repo_error_on_the_wire(no_repo: None) -> None:
    wire = await task_index_set(continuation_prompt="Resume", cwd="/tmp")

    assert wire["error"] == "Not in a git repository"
