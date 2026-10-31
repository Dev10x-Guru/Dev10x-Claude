from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from dev10x.ci_review import gh_shim
from dev10x.ci_review.gh_shim import classify, main, write_shim
from dev10x.ci_review.outbox import read_entries


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], "read"),
        (["pr", "view", "1"], "read"),
        (["pr"], "write"),
        (["pr", "diff", "1"], "read"),
        (["pr", "create", "--fill"], "write"),
        (["repo", "view"], "read"),
        (["repo", "delete", "o/r"], "write"),
        (["run", "view", "9"], "read"),
        (["auth", "status"], "read"),
        (["--version"], "read"),
        (["label", "create", "x"], "write"),
        (["workflow", "run", "ci.yml"], "write"),
        (["release", "create", "v1"], "write"),
        (["pr", "review", "1", "--comment"], "write"),
        (["pr", "ready", "1", "--undo"], "write"),
        (["pr", "edit", "1"], "write"),
        (["pr", "comment", "1", "-b", "x"], "write"),
        (["pr", "merge", "1"], "write"),
        (["pr", "close", "1"], "write"),
        (["issue", "view", "1"], "read"),
        (["issue", "comment", "1"], "write"),
        (["issue", "edit", "1"], "write"),
        (["issue", "close", "1"], "write"),
        (["search", "prs"], "read"),
        (["api", "repos/o/r/pulls/1"], "read"),
        (["api", "--paginate", "repos/o/r/pulls/1/comments", "--jq", ".[]"], "read"),
        (["api", "-X", "DELETE", "repos/o/r/pulls/comments/9"], "write"),
        (["api", "-XPOST", "repos/o/r/issues/1/comments"], "write"),
        (["api", "--method=PATCH", "repos/o/r/issues/comments/1"], "write"),
        (["api", "--method", "GET", "-f", "q=x", "search/issues"], "read"),
        (["api", "-X", "get", "repos/o/r"], "read"),
        (["api", "repos/o/r/issues/1/comments", "-f", "body=hi"], "write"),
        (["api", "repos/o/r/issues/1/comments", "--input", "-"], "write"),
        (["api", "repos/o/r/issues/1/comments", "-Fbody=hi"], "write"),
        (["api", "graphql", "-f", "query=query { viewer { login } }"], "read"),
        (["api", "graphql", "-f", "query=mutation { x }"], "write"),
        (["api", "graphql", "--raw-field=query=Mutation { x }"], "write"),
        (["api", "graphql", "-F", "owner=o"], "read"),
    ],
)
def test_classify(argv: list[str], expected: str) -> None:
    assert classify(argv=argv) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [("mutation M { resolve }", "write"), ("query Q { x }", "read")],
)
def test_classify_reads_graphql_query_file(tmp_path: Path, content: str, expected: str) -> None:
    query = tmp_path / "q.graphql"
    query.write_text(content, encoding="utf-8")

    assert classify(argv=["api", "graphql", "-F", f"query=@{query}"]) == expected


def test_classify_missing_query_file_is_read(tmp_path: Path) -> None:
    assert classify(argv=["api", "graphql", "-F", f"query=@{tmp_path / 'gone'}"]) == "read"


class TestMain:
    @pytest.fixture
    def outbox(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "outbox.jsonl"
        monkeypatch.setenv("DEV10X_CI_OUTBOX", str(path))
        monkeypatch.setenv("DEV10X_CI_REAL_GH", "/real/gh")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "body.md").write_text("Finding body\n", encoding="utf-8")
        return path

    @pytest.fixture
    def execs(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[str]]]:
        calls: list[tuple[str, list[str]]] = []
        monkeypatch.setattr(os, "execv", lambda path, args: calls.append((path, args)))
        return calls

    def test_read_execs_real_gh(self, outbox: Path, execs: list[tuple[str, list[str]]]) -> None:
        assert main(argv=["pr", "view", "1"]) == 0
        assert execs == [("/real/gh", ["/real/gh", "pr", "view", "1"])]
        assert read_entries(path=outbox) == []

    def test_write_records_and_prints_empty_object(
        self,
        outbox: Path,
        execs: list[tuple[str, list[str]]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert main(argv=["pr", "comment", "1", "--body-file", "body.md"]) == 0

        (entry,) = read_entries(path=outbox)
        assert capsys.readouterr().out == "{}\n"
        assert execs == []
        assert entry["argv"] == ["gh", "pr", "comment", "1", "--body-file", "body.md"]
        assert entry["body_file_content"] == "Finding body\n"
        assert entry["kind"] == "gh"
        assert "stdin" not in entry

    @pytest.mark.parametrize(
        "argv",
        [
            ["pr", "comment", "1", "-F", "body.md"],
            ["pr", "comment", "1", "--body-file=body.md"],
            ["api", "-X", "PATCH", "repos/o/r/issues/comments/1", "-F", "body=@body.md"],
        ],
        ids=["short-flag", "equals", "api-field"],
    )
    def test_body_file_forms(
        self, outbox: Path, execs: list[tuple[str, list[str]]], argv: list[str]
    ) -> None:
        main(argv=argv)

        (entry,) = read_entries(path=outbox)
        assert entry["body_file_content"] == "Finding body\n"

    @pytest.mark.parametrize(
        "argv",
        [
            ["api", "repos/o/r/issues/1/comments", "--input", "-"],
            ["pr", "comment", "1", "--body-file", "-"],
        ],
        ids=["input", "body-file"],
    )
    def test_stdin_is_captured(
        self,
        outbox: Path,
        execs: list[tuple[str, list[str]]],
        monkeypatch: pytest.MonkeyPatch,
        argv: list[str],
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO('{"body": "x"}'))

        main(argv=argv)

        (entry,) = read_entries(path=outbox)
        assert entry["stdin"] == '{"body": "x"}'
        assert "body_file_content" not in entry

    def test_api_field_without_body_file(
        self, outbox: Path, execs: list[tuple[str, list[str]]]
    ) -> None:
        main(argv=["api", "repos/o/r/issues/1/comments", "-F", "x=1"])

        (entry,) = read_entries(path=outbox)
        assert "body_file_content" not in entry

    def test_defaults_to_sys_argv(
        self,
        outbox: Path,
        execs: list[tuple[str, list[str]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("sys.argv", ["gh", "repo", "view"])

        main()

        assert execs == [("/real/gh", ["/real/gh", "repo", "view"])]


class TestWriteShim:
    @pytest.fixture
    def fake_python(self, tmp_path: Path) -> Path:
        path = tmp_path / "python"
        path.write_text('#!/bin/bash\necho "$DEV10X_CI_REAL_GH|$*"\n', encoding="utf-8")
        path.chmod(0o755)
        return path

    @pytest.fixture
    def shim(self, tmp_path: Path, fake_python: Path) -> Path:
        return write_shim(
            bin_dir=tmp_path / "bin", python=str(fake_python), real_gh="/opt/my gh/gh"
        )

    def test_is_executable(self, shim: Path) -> None:
        assert os.access(shim, os.X_OK)

    def test_defaults_real_gh_and_execs_module(self, shim: Path) -> None:
        result = subprocess.run(
            [str(shim), "pr", "view"],
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.stdout == "/opt/my gh/gh|-I -m dev10x.ci_review.gh_shim pr view\n"


def test_outbox_entry_is_json_lines(tmp_path: Path) -> None:
    outbox = tmp_path / "o.jsonl"
    gh_shim.record_write(argv=["pr", "merge", "1"], outbox=outbox, cwd=str(tmp_path), stdin=None)

    assert json.loads(outbox.read_text(encoding="utf-8"))["argv"] == ["gh", "pr", "merge", "1"]
