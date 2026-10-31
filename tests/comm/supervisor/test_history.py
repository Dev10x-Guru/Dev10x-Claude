"""Tests for listing a project's past sessions to resume (GH-1722)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from dev10x.comm.supervisor import history
from dev10x.comm.supervisor.history import (
    PastSession,
    read_past_session,
    read_past_sessions,
    transcript_folder,
)

WT = "/work/.herdr/worktrees/Dev10x-Claude/poc"
ROOT = "/work/dx/Dev10x-Claude"


def _write(*, folder: Path, session_id: str, records: list[Any], mtime: float) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\nnot json\n")
    os.utime(path, (mtime, mtime))
    return path


def _prompt(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"content": text}}


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    _write(
        folder=root / transcript_folder(cwd=WT),
        session_id="named",
        records=[
            _prompt("Build the supervisor page"),
            {"type": "custom-title", "customTitle": "old-title"},
            {"type": "custom-title", "customTitle": "GH-1722-status-bar"},
        ],
        mtime=1_000,
    )
    _write(
        folder=root / transcript_folder(cwd=WT),
        session_id="recent",
        records=[
            {"type": "user", "isMeta": True, "message": {"content": "hook text"}},
            _prompt("<command-name>/clear</command-name>"),
            {"type": "user", "message": {"content": [{"type": "text", "text": "list form"}]}},
            _prompt("Fix   the\nflaky test " + "x" * 100),
        ],
        mtime=3_000,
    )
    _write(
        folder=root / transcript_folder(cwd=ROOT),
        session_id="older",
        records=[_prompt("Release notes")],
        mtime=2_000,
    )
    _write(
        folder=root / transcript_folder(cwd=ROOT),
        session_id="running",
        records=[_prompt("I am live")],
        mtime=9_000,
    )
    return root


def test_transcript_folder_matches_claude_code() -> None:
    assert transcript_folder(cwd=WT) == "-work--herdr-worktrees-Dev10x-Claude-poc"


class TestReadPastSessions:
    def test_named_first_then_most_recent(self, projects: Path) -> None:
        past = read_past_sessions(
            checkouts=[ROOT, WT], running={"running"}, projects_root=projects
        )

        assert [(item.session_id, item.cwd, item.named) for item in past] == [
            ("named", WT, True),
            ("recent", WT, False),
            ("older", ROOT, False),
        ]

    def test_titles_and_topics(self, projects: Path) -> None:
        named, recent, _ = read_past_sessions(
            checkouts=[ROOT, WT], running={"running"}, projects_root=projects
        )

        assert (named.title, named.topic, recent.title, recent.topic) == (
            "GH-1722-status-bar",
            "Build the supervisor page",
            "",
            "Fix the flaky test " + "x" * 71 + "…",
        )

    def test_limit(self, projects: Path) -> None:
        assert (
            len(
                read_past_sessions(
                    checkouts=[ROOT, WT], running=set(), projects_root=projects, limit=2
                )
            )
            == 2
        )

    def test_unknown_checkout_has_no_history(self, projects: Path) -> None:
        assert (
            read_past_sessions(checkouts=["/nowhere"], running=set(), projects_root=projects) == []
        )

    def test_unreadable_transcript_is_skipped(
        self, projects: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(**kwargs: Any) -> tuple[bytes, bytes]:
            raise OSError("gone")

        monkeypatch.setattr(history, "_ends", broken)

        assert (
            read_past_sessions(checkouts=[ROOT, WT], running=set(), projects_root=projects) == []
        )


def test_defaults_to_claude_dir(projects: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history.ClaudeDir, "projects_dir", staticmethod(lambda: projects))

    assert [item.session_id for item in read_past_sessions(checkouts=[ROOT], running=set())] == [
        "running",
        "older",
    ]


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        (
            "<command-message>dev10x:work-on</command-message>\n"
            "<command-name>/dev10x:work-on</command-name>\n"
            "<command-args>Stop the Stop hook\nfrom being noisy</command-args>",
            "/dev10x:work-on Stop the Stop hook from being noisy",
        ),
        ("<command-name>/my:reflect</command-name>", "/my:reflect"),
        ("<system-reminder>only markup</system-reminder>", ""),
    ],
    ids=["command-with-args", "bare-command", "markup"],
)
def test_slash_command_topics(tmp_path: Path, text: str, topic: str) -> None:
    path = _write(folder=tmp_path, session_id="cmd", records=[_prompt(text)], mtime=5)

    assert read_past_session(path=path, cwd=ROOT).topic == topic  # type: ignore[union-attr]


def test_read_past_session_without_prompts(tmp_path: Path) -> None:
    path = _write(folder=tmp_path, session_id="empty", records=[{"type": "summary"}], mtime=5)

    past = read_past_session(path=path, cwd=ROOT)

    assert isinstance(past, PastSession)
    assert (past.title, past.topic, past.named) == ("", "", False)
