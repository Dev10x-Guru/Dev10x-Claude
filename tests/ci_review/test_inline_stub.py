from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from dev10x.ci_review import inline_stub
from dev10x.ci_review.inline_stub import (
    FAKE_COMMENT_ID_BASE,
    FAKE_COMMENT_ID_BITS,
    create_inline_comment,
    fake_comment_id,
)
from dev10x.ci_review.outbox import read_entries


@pytest.fixture
def outbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("DEV10X_CI_OUTBOX", str(path))
    return path


def test_records_and_returns_the_action_shape(
    outbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = iter([FAKE_COMMENT_ID_BASE + 11, FAKE_COMMENT_ID_BASE + 7])
    monkeypatch.setattr(inline_stub, "fake_comment_id", lambda: next(ids))

    first = json.loads(create_inline_comment(path="a.py", body="one", line=3))
    second = json.loads(create_inline_comment(path="b.py", body="two", startLine=5))

    assert first == {
        "success": True,
        "comment_id": FAKE_COMMENT_ID_BASE + 11,
        "html_url": None,
        "path": "a.py",
        "line": 3,
        "message": "Inline comment recorded to the dev10x ci-review outbox (dry run)",
    }
    assert second["line"] == 5
    assert [entry["comment_id"] for entry in read_entries(path=outbox)] == [
        FAKE_COMMENT_ID_BASE + 11,
        FAKE_COMMENT_ID_BASE + 7,
    ]
    assert read_entries(path=outbox)[0]["side"] == "RIGHT"


def test_fake_ids_do_not_depend_on_the_outbox(outbox: Path) -> None:
    ids = {fake_comment_id() for _ in range(50)}

    assert len(ids) == 50
    assert min(ids) >= FAKE_COMMENT_ID_BASE
    assert max(ids) < FAKE_COMMENT_ID_BASE + 2**FAKE_COMMENT_ID_BITS


def test_fake_id_is_drawn_from_a_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inline_stub.uuid, "uuid4", lambda: uuid.UUID(int=(5 << 88) | 123))

    assert fake_comment_id() == FAKE_COMMENT_ID_BASE + 5


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
