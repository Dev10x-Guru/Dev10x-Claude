"""Tests for previewing the tool call a session is waiting to run (GH-1692)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.claude_paths import CLAUDE_HOME_ENV_VAR, ClaudeDir

from dev10x.comm.supervisor import pending
from dev10x.comm.supervisor.pending import (
    PendingTool,
    Preview,
    RecentTool,
    build_preview,
    find_transcript,
    read_pending_tool,
    read_preview,
    read_recent_tools,
    read_session_commands,
)

SESSION = "47a1ef74-ca1e-4876-bdb1-83dd7a452919"


def _use(*, tool_id: str, name: str, tool_input: Any) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]
        },
    }


def _result(*, tool_id: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id}]},
    }


def _write(*, path: Path, records: list[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    return tmp_path / "projects"


class TestDefaultRoot:
    def test_resolves_through_claude_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(CLAUDE_HOME_ENV_VAR, str(tmp_path / "claude"))
        ClaudeDir.reset_cache()
        path = _write(
            path=tmp_path / "claude" / "projects" / "-w" / f"{SESSION}.jsonl", records=[]
        )
        try:
            found = find_transcript(session_id=SESSION)
        finally:
            ClaudeDir.reset_cache()

        assert found == path


class TestFindTranscript:
    def test_finds_by_session_id(self, projects: Path) -> None:
        path = _write(path=projects / "-work-x" / f"{SESSION}.jsonl", records=[])

        assert find_transcript(session_id=SESSION, projects_root=projects) == path

    def test_missing(self, projects: Path) -> None:
        assert find_transcript(session_id=SESSION, projects_root=projects) is None


class TestReadPendingTool:
    def test_returns_the_last_unanswered_call(self, tmp_path: Path) -> None:
        path = _write(
            path=tmp_path / "t.jsonl",
            records=[
                _use(tool_id="a", name="Read", tool_input={"file_path": "x"}),
                _result(tool_id="a"),
                _use(tool_id="b", name="Bash", tool_input={"command": "ls"}),
                "not a record",
                {"message": {"content": "plain text"}},
            ],
        )
        path.write_text(path.read_text() + "{broken json\n")

        assert read_pending_tool(path=path) == PendingTool(name="Bash", input={"command": "ls"})

    def test_none_when_everything_answered(self, tmp_path: Path) -> None:
        path = _write(
            path=tmp_path / "t.jsonl",
            records=[_use(tool_id="a", name="Bash", tool_input={}), _result(tool_id="a")],
        )

        assert read_pending_tool(path=path) is None

    def test_non_dict_input_becomes_empty(self, tmp_path: Path) -> None:
        path = _write(
            path=tmp_path / "t.jsonl", records=[_use(tool_id="a", name="X", tool_input=[1])]
        )

        assert read_pending_tool(path=path) == PendingTool(name="X", input={})

    def test_reads_only_the_tail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pending, "TAIL_BYTES", 200)
        path = _write(
            path=tmp_path / "t.jsonl",
            records=[_use(tool_id="old", name="Old", tool_input={"pad": "x" * 300})]
            + [_use(tool_id="new", name="Bash", tool_input={"command": "pwd"})],
        )

        assert read_pending_tool(path=path) == PendingTool(name="Bash", input={"command": "pwd"})


class TestBuildPreview:
    def test_edit_is_a_unified_diff(self) -> None:
        preview = build_preview(
            tool=PendingTool(
                name="Edit",
                input={"file_path": "src/a.py", "old_string": "x = 1\n", "new_string": "x = 2\n"},
            )
        )

        assert (preview.kind, preview.title, preview.body.splitlines()[2:]) == (
            "diff",
            "src/a.py",
            ["@@ -1 +1 @@", "-x = 1", "+x = 2"],
        )

    def test_multiedit_concatenates(self) -> None:
        preview = build_preview(
            tool=PendingTool(
                name="MultiEdit",
                input={
                    "file_path": "a.py",
                    "edits": [
                        {"old_string": "a", "new_string": "b"},
                        {"old_string": "c", "new_string": "d"},
                        "junk",
                    ],
                },
            )
        )

        assert [
            line
            for line in preview.body.splitlines()
            if line[:1] in "+-" and line[:3] not in ("---", "+++")
        ] == [
            "-a",
            "+b",
            "-c",
            "+d",
        ]

    def test_write_diffs_against_the_file_on_disk(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("one\ntwo\n")

        preview = build_preview(
            tool=PendingTool(
                name="Write", input={"file_path": str(target), "content": "one\nthree\n"}
            )
        )

        assert preview.body.splitlines()[-2:] == ["-two", "+three"]

    def test_write_new_file_is_all_added(self, tmp_path: Path) -> None:
        preview = build_preview(
            tool=PendingTool(
                name="Write", input={"file_path": str(tmp_path / "new.txt"), "content": "hi\n"}
            )
        )

        assert preview.body.splitlines()[-1] == "+hi"

    def test_write_skips_huge_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pending, "MAX_FILE_BYTES", 2)
        target = tmp_path / "big.txt"
        target.write_text("long text\n")

        preview = build_preview(
            tool=PendingTool(name="Write", input={"file_path": str(target), "content": "x\n"})
        )

        assert preview.body.splitlines()[-1] == "+x"

    def test_bash_shows_command_and_description(self) -> None:
        assert build_preview(
            tool=PendingTool(name="Bash", input={"command": "ls -la", "description": "List files"})
        ) == Preview(tool="Bash", title="List files", kind="command", body="ls -la")

    def test_other_tools_show_json(self) -> None:
        preview = build_preview(tool=PendingTool(name="mcp__x__y", input={"a": 1}))

        assert (preview.kind, json.loads(preview.body)) == ("text", {"a": 1})

    def test_long_bodies_are_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pending, "MAX_PREVIEW_LINES", 2)

        preview = build_preview(tool=PendingTool(name="Bash", input={"command": "a\nb\nc"}))

        assert (preview.body, preview.truncated) == ("a\nb", True)


class TestReadSessionCommands:
    def test_distinct_bash_commands_in_order(self, projects: Path) -> None:
        _write(
            path=projects / "-w" / f"{SESSION}.jsonl",
            records=[
                _use(tool_id="a", name="Bash", tool_input={"command": "git status"}),
                _use(tool_id="b", name="Read", tool_input={"file_path": "x"}),
                _use(tool_id="c", name="Bash", tool_input={"command": " herdr agent list "}),
                _use(tool_id="d", name="Bash", tool_input={"command": "git status"}),
                _use(tool_id="e", name="Bash", tool_input={"command": ""}),
                _result(tool_id="a"),
            ],
        )

        assert read_session_commands(session_id=SESSION, projects_root=projects) == [
            "git status",
            "herdr agent list",
        ]

    def test_keeps_the_most_recent(self, projects: Path) -> None:
        _write(
            path=projects / "-w" / f"{SESSION}.jsonl",
            records=[
                _use(tool_id=str(i), name="Bash", tool_input={"command": f"cmd {i}"})
                for i in range(5)
            ],
        )

        assert read_session_commands(session_id=SESSION, projects_root=projects, limit=2) == [
            "cmd 3",
            "cmd 4",
        ]

    def test_no_transcript(self, projects: Path) -> None:
        assert read_session_commands(session_id=SESSION, projects_root=projects) == []

    def test_unreadable_transcript(self, projects: Path) -> None:
        path = _write(path=projects / "-w" / f"{SESSION}.jsonl", records=[])
        path.chmod(0)
        try:
            commands = read_session_commands(session_id=SESSION, projects_root=projects)
        finally:
            path.chmod(0o600)

        assert commands == []


def _outcome(*, tool_id: str, text: Any, is_error: bool) -> dict[str, Any]:
    item = {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}
    return {"type": "user", "message": {"content": [item]}}


class TestReadRecentTools:
    def test_newest_first_with_outcomes(self, projects: Path) -> None:
        _write(
            path=projects / "-w" / f"{SESSION}.jsonl",
            records=[
                _use(tool_id="a", name="Bash", tool_input={"command": " git status "}),
                _result(tool_id="a"),
                _use(tool_id="b", name="Edit", tool_input={"file_path": "/r/a.py"}),
                _outcome(
                    tool_id="b",
                    text="The user doesn't want to proceed with this tool use.",
                    is_error=True,
                ),
                _use(tool_id="c", name="WebFetch", tool_input={"url": "https://x.dev"}),
                _outcome(tool_id="c", text=[{"type": "text", "text": "404"}], is_error=True),
                _use(tool_id="d", name="TaskList", tool_input={}),
            ],
        )

        assert read_recent_tools(session_id=SESSION, projects_root=projects) == [
            RecentTool(tool="TaskList", target="", outcome="pending"),
            RecentTool(tool="WebFetch", target="https://x.dev", outcome="failed"),
            RecentTool(tool="Edit", target="/r/a.py", outcome="rejected"),
            RecentTool(tool="Bash", target="git status", outcome="ran", command="git status"),
        ]

    def test_keeps_the_most_recent(self, projects: Path) -> None:
        _write(
            path=projects / "-w" / f"{SESSION}.jsonl",
            records=[
                _use(tool_id=str(i), name="Grep", tool_input={"pattern": f"p{i}"})
                for i in range(4)
            ],
        )

        recent = read_recent_tools(session_id=SESSION, projects_root=projects, limit=2)

        assert [tool.target for tool in recent] == ["p3", "p2"]

    def test_no_transcript(self, projects: Path) -> None:
        assert read_recent_tools(session_id=SESSION, projects_root=projects) == []

    def test_unreadable_transcript(self, projects: Path) -> None:
        path = _write(path=projects / "-w" / f"{SESSION}.jsonl", records=[])
        path.chmod(0)
        try:
            recent = read_recent_tools(session_id=SESSION, projects_root=projects)
        finally:
            path.chmod(0o600)

        assert recent == []


class TestReadPreview:
    def test_end_to_end(self, projects: Path) -> None:
        _write(
            path=projects / "-work-x" / f"{SESSION}.jsonl",
            records=[_use(tool_id="a", name="Bash", tool_input={"command": "pwd"})],
        )

        preview = read_preview(session_id=SESSION, projects_root=projects)

        assert preview is not None and preview.body == "pwd"

    def test_no_transcript(self, projects: Path) -> None:
        assert read_preview(session_id=SESSION, projects_root=projects) is None

    def test_nothing_pending(self, projects: Path) -> None:
        _write(path=projects / "-w" / f"{SESSION}.jsonl", records=[])

        assert read_preview(session_id=SESSION, projects_root=projects) is None

    def test_unreadable_transcript(self, projects: Path) -> None:
        path = _write(path=projects / "-w" / f"{SESSION}.jsonl", records=[])
        path.chmod(0)
        try:
            preview = read_preview(session_id=SESSION, projects_root=projects)
        finally:
            path.chmod(0o600)

        assert preview is None
