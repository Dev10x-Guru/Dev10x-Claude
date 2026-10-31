from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev10x.ci_review import inline_stub
from dev10x.ci_review.inline_stub import FAKE_COMMENT_ID_BASE, create_inline_comment
from dev10x.ci_review.outbox import read_entries


@pytest.fixture
def outbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("DEV10X_CI_OUTBOX", str(path))
    return path


def test_records_and_returns_the_action_shape(outbox: Path) -> None:
    first = json.loads(create_inline_comment(path="a.py", body="one", line=3))
    second = json.loads(create_inline_comment(path="b.py", body="two", startLine=5))

    assert first == {
        "success": True,
        "comment_id": FAKE_COMMENT_ID_BASE + 1,
        "html_url": None,
        "path": "a.py",
        "line": 3,
        "message": "Inline comment recorded to the dev10x ci-review outbox (dry run)",
    }
    assert second["comment_id"] == FAKE_COMMENT_ID_BASE + 2
    assert second["line"] == 5
    assert [entry["kind"] for entry in read_entries(path=outbox)] == ["inline_comment"] * 2
    assert read_entries(path=outbox)[0]["side"] == "RIGHT"


def test_requires_a_line(outbox: Path) -> None:
    with pytest.raises(ValueError, match="line or startLine"):
        create_inline_comment(path="a.py", body="x")

    assert read_entries(path=outbox) == []


def test_server_is_named_like_the_action() -> None:
    assert inline_stub.server.name == "github_inline_comment"


def test_main_runs_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[bool] = []
    monkeypatch.setattr(inline_stub.server, "run", lambda: runs.append(True))

    assert inline_stub.main() == 0
    assert runs == [True]
