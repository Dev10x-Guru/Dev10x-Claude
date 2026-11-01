"""Rehomed park/session task index — read, append, wrap-up state (GH-1009).

The behaviour that matters: the store lives outside every repo, one index per
repo (not per worktree), and a leftover retired `.claude/Dev10x/session.yaml`
is ignored since its read fallback was removed (GH-1771).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from dev10x.domain.common.result import ErrorResult

from dev10x.session import preset_pin, task_index


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend every call comes from a worktree of the `Dev10x-Claude` repo."""
    main = tmp_path / "work" / "Dev10x-Claude"
    (main / ".git").mkdir(parents=True)
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(main / ".git"))
    return main


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A sibling checkout of the same repo, where a legacy file may linger."""
    path = tmp_path / "work" / ".worktrees" / "Dev10x-Claude-1"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def store(repo: Path) -> Path:
    """Path the rehomed index resolves to, isolated to a tmp home by conftest."""
    from dev10x.domain.dev10x_paths import Dev10xConfigDir

    return Dev10xConfigDir.task_index_yaml(repo_name="Dev10x-Claude")


@pytest.fixture
def stored(store: Path) -> Any:
    def read() -> dict[str, Any]:
        return yaml.safe_load(store.read_text()) or {}

    return read


@pytest.fixture
def legacy_file() -> Any:
    """Write a retired-location file under an arbitrary checkout root."""

    def write(root: Path, content: dict[str, Any]) -> Path:
        path = root / ".claude" / "Dev10x" / "session.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(content))
        return path

    return write


@pytest.fixture
def no_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
    monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)


# --- read -------------------------------------------------------------


def test_read_index_reports_the_rehomed_path_outside_every_repo(store: Path, repo: Path) -> None:
    """The AC: nothing resolves under a repo's .claude/ any more."""
    result = task_index.read_index(cwd=str(repo))

    assert result.value["path"] == str(store)
    assert ".claude" not in result.value["path"]


def test_read_index_on_a_missing_store_returns_empty_sections(repo: Path) -> None:
    payload = task_index.read_index(cwd=str(repo)).value

    assert payload["exists"] is False
    assert payload["tasks"] == []
    assert payload["insights"] == []
    assert payload["tickets"] == []
    assert payload["continuation_prompt"] is None


def test_read_index_returns_stored_sections(store: Path, repo: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        yaml.safe_dump(
            {
                "tasks": [{"subject": "Wire retries", "source": "park"}],
                "continuation_prompt": "Resume the retry work",
                "insights": ["batch the writes"],
                "branch": "janusz/GH-1/x",
                "tickets": ["GH-1"],
                "wrapped_at": "2026-08-03T10:00:00Z",
            }
        )
    )

    payload = task_index.read_index(cwd=str(repo)).value

    assert payload["exists"] is True
    assert payload["tasks"] == [{"subject": "Wire retries", "source": "park"}]
    assert payload["continuation_prompt"] == "Resume the retry work"
    assert payload["insights"] == ["batch the writes"]
    assert payload["branch"] == "janusz/GH-1/x"
    assert payload["tickets"] == ["GH-1"]
    assert payload["wrapped_at"] == "2026-08-03T10:00:00Z"


@pytest.mark.parametrize("checkout", ["repo", "worktree"])
def test_read_index_ignores_a_leftover_retired_file(
    request: pytest.FixtureRequest, repo: Path, legacy_file: Any, checkout: str
) -> None:
    """GH-1771: the retired per-checkout file is no longer a fallback."""
    root = request.getfixturevalue(checkout)
    legacy_file(root, {"tasks": [{"subject": "Old item", "source": "park"}]})

    payload = task_index.read_index(cwd=str(root)).value

    assert payload["exists"] is False
    assert payload["tasks"] == []
    assert "legacy_read" not in payload


def test_read_index_errors_on_a_corrupt_store(store: Path, repo: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("tasks: [unclosed\n")

    result = task_index.read_index(cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert "unreadable" in result.error


def test_read_index_errors_when_the_store_is_not_a_mapping(store: Path, repo: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("- a list\n")

    result = task_index.read_index(cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert "not a mapping" in result.error


def test_read_index_errors_outside_a_git_repository(no_repo: None) -> None:
    result = task_index.read_index(cwd="/tmp")

    assert isinstance(result, ErrorResult)
    assert result.error == "Not in a git repository"


# --- append -----------------------------------------------------------


@pytest.mark.parametrize("missing", ["subject", "source"])
def test_append_task_requires_subject_and_source(repo: Path, missing: str) -> None:
    entry = {"subject": "Wire retries", "source": "park"}
    entry.pop(missing)

    result = task_index.append_task(entry=entry, cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert missing in result.error


def test_append_task_writes_the_entry(repo: Path, stored: Any) -> None:
    result = task_index.append_task(
        entry={"subject": "Wire retries", "status": "pending", "source": "park"},
        cwd=str(repo),
    )

    assert result.value["task_count"] == 1
    assert stored()["tasks"] == [
        {"subject": "Wire retries", "status": "pending", "source": "park"}
    ]
    assert stored()["repo"] == "Dev10x-Claude"


def test_append_task_accumulates_across_worktrees_of_one_repo(
    repo: Path, worktree: Path, stored: Any
) -> None:
    """The AC: repo-scoped, so a sibling worktree appends to the same index."""
    task_index.append_task(entry={"subject": "First", "source": "park"}, cwd=str(repo))
    task_index.append_task(entry={"subject": "Second", "source": "park"}, cwd=str(worktree))

    assert [task["subject"] for task in stored()["tasks"]] == ["First", "Second"]


def test_append_task_does_not_fold_a_leftover_retired_file(
    repo: Path, worktree: Path, legacy_file: Any, stored: Any
) -> None:
    legacy_file(worktree, {"tasks": [{"subject": "Old item", "source": "park"}]})

    result = task_index.append_task(
        entry={"subject": "New item", "source": "park"}, cwd=str(worktree)
    )

    assert "folded_legacy" not in result.value
    assert [task["subject"] for task in stored()["tasks"]] == ["New item"]


def test_append_task_errors_on_a_non_list_tasks_key(store: Path, repo: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(yaml.safe_dump({"tasks": "not a list"}))

    result = task_index.append_task(entry={"subject": "X", "source": "park"}, cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert "non-list" in result.error


def test_append_task_errors_on_a_corrupt_store(store: Path, repo: Path) -> None:
    """GH-1413: an unreadable store surfaces as err(), not as a raise."""
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("tasks:\n  - subject: 'unterminated\n")

    result = task_index.append_task(entry={"subject": "X", "source": "park"}, cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert "not valid YAML" in result.error


def test_append_task_leaves_a_corrupt_store_untouched(store: Path, repo: Path) -> None:
    corrupt = "tasks:\n  - subject: 'unterminated\n"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(corrupt)

    task_index.append_task(entry={"subject": "X", "source": "park"}, cwd=str(repo))

    assert store.read_text() == corrupt


def test_set_session_state_errors_on_a_corrupt_store(store: Path, repo: Path) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("branch: 'unterminated\n")

    result = task_index.set_session_state(branch="feature", cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert "not valid YAML" in result.error


def test_append_task_errors_outside_a_git_repository(no_repo: None) -> None:
    result = task_index.append_task(entry={"subject": "X", "source": "park"}, cwd="/tmp")

    assert isinstance(result, ErrorResult)
    assert result.error == "Not in a git repository"


# --- wrap-up state ----------------------------------------------------


def test_set_session_state_writes_supplied_fields(repo: Path, stored: Any) -> None:
    result = task_index.set_session_state(
        continuation_prompt="Resume the retry work",
        insights=["batch the writes"],
        branch="janusz/GH-1/x",
        tickets=["GH-1"],
        wrapped_at="2026-08-03T10:00:00Z",
        cwd=str(repo),
    )

    assert result.value["updated_keys"] == [
        "branch",
        "continuation_prompt",
        "insights",
        "tickets",
        "wrapped_at",
    ]
    assert stored()["continuation_prompt"] == "Resume the retry work"
    assert stored()["wrapped_at"] == "2026-08-03T10:00:00Z"


def test_set_session_state_preserves_parked_tasks(repo: Path, stored: Any) -> None:
    """Refreshing the prompt must not blank the park family's entries."""
    task_index.append_task(entry={"subject": "Wire retries", "source": "park"}, cwd=str(repo))

    task_index.set_session_state(continuation_prompt="Resume", cwd=str(repo))

    assert stored()["tasks"] == [{"subject": "Wire retries", "source": "park"}]
    assert stored()["continuation_prompt"] == "Resume"


def test_set_session_state_does_not_fold_a_leftover_retired_file(
    repo: Path, worktree: Path, legacy_file: Any, stored: Any
) -> None:
    legacy_file(worktree, {"tasks": [{"subject": "Old item", "source": "park"}]})

    result = task_index.set_session_state(continuation_prompt="Resume", cwd=str(worktree))

    assert "folded_legacy" not in result.value
    assert "tasks" not in stored()


def test_set_session_state_needs_at_least_one_field(repo: Path) -> None:
    result = task_index.set_session_state(cwd=str(repo))

    assert isinstance(result, ErrorResult)
    assert "at least one field" in result.error


def test_set_session_state_errors_outside_a_git_repository(no_repo: None) -> None:
    result = task_index.set_session_state(continuation_prompt="Resume", cwd="/tmp")

    assert isinstance(result, ErrorResult)
    assert result.error == "Not in a git repository"
