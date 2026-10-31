from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev10x.ci_review import runner
from dev10x.ci_review.runner import (
    Auth,
    Invocation,
    build_invocation,
    parse_stream,
    resolve_auth,
    run_claude,
    write_mcp_config,
)
from dev10x.core.domain.common.result import ErrorResult, SuccessResult


class TestBuildInvocation:
    @pytest.fixture
    def invocation(self, tmp_path: Path) -> Invocation:
        return build_invocation(
            claude=Path("/cli/claude"),
            prompt="Review.\nRUN CONTEXT:",
            claude_args=["--model", "sonnet"],
            run_dir=tmp_path,
            checkout=tmp_path / "checkout",
            home="/home/me",
            repo="owner/name",
            pr=12,
            real_gh="/usr/bin/gh",
            auth=Auth(env={"ANTHROPIC_API_KEY": "k"}, notional=False),
            node_dir=Path("/opt/node/bin"),
        )

    def test_argv(self, invocation: Invocation, tmp_path: Path) -> None:
        assert invocation.argv == [
            "/cli/claude",
            "-p",
            "Review.\nRUN CONTEXT:",
            "--model",
            "sonnet",
            "--output-format",
            "stream-json",
            "--verbose",
            "--mcp-config",
            str(tmp_path / "mcp.json"),
            "--strict-mcp-config",
        ]
        assert invocation.cwd == tmp_path / "checkout"

    def test_env_is_minimal(self, invocation: Invocation, tmp_path: Path) -> None:
        assert invocation.env == {
            "PATH": f"{tmp_path / 'bin'}:/opt/node/bin:/usr/bin:/bin",
            "HOME": "/home/me",
            "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
            "CI": "true",
            "GITHUB_ACTIONS": "true",
            "CLAUDE_CODE_ACTION": "1",
            "DETAILED_PERMISSION_MESSAGES": "1",
            "SHELL": "/bin/bash",
            "GITHUB_REPOSITORY": "owner/name",
            "PR_NUMBER": "12",
            "REPO_OWNER": "owner",
            "REPO_NAME": "name",
            "DEV10X_CI_OUTBOX": str(tmp_path / "outbox.jsonl"),
            "DEV10X_CI_REAL_GH": "/usr/bin/gh",
            "ANTHROPIC_API_KEY": "k",
        }

    def test_path_without_node(self, tmp_path: Path) -> None:
        invocation = build_invocation(
            claude=Path("c"),
            prompt="p",
            claude_args=[],
            run_dir=tmp_path,
            checkout=tmp_path,
            home="/h",
            repo="o/n",
            pr=1,
            real_gh="gh",
            auth=Auth(env={}, notional=True),
            node_dir=None,
        )

        assert invocation.env["PATH"] == f"{tmp_path / 'bin'}:/usr/bin:/bin"


class TestResolveAuth:
    @pytest.fixture
    def config_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "run" / "config"

    @pytest.fixture
    def credentials(self, tmp_path: Path) -> Path:
        home = tmp_path / "claude-home"
        home.mkdir()
        path = home / ".credentials.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def test_api_key_is_real_cost(self, config_dir: Path) -> None:
        result = resolve_auth(environ={"ANTHROPIC_API_KEY": "sk"}, config_dir=config_dir)

        assert result == SuccessResult(value=Auth(env={"ANTHROPIC_API_KEY": "sk"}, notional=False))
        assert not config_dir.exists()

    def test_config_dir_credentials_are_linked(self, config_dir: Path, credentials: Path) -> None:
        environ = {"CLAUDE_CONFIG_DIR": str(credentials.parent)}

        first = resolve_auth(environ=environ, config_dir=config_dir)
        second = resolve_auth(environ=environ, config_dir=config_dir)

        assert first == second == SuccessResult(value=Auth(env={}, notional=True))
        assert (config_dir / ".credentials.json").resolve() == credentials

    def test_default_claude_home(
        self, config_dir: Path, credentials: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner.ClaudeDir, "home", classmethod(lambda cls: credentials.parent))

        result = resolve_auth(environ={}, config_dir=config_dir)

        assert isinstance(result, SuccessResult)

    def test_no_credentials(self, config_dir: Path, tmp_path: Path) -> None:
        result = resolve_auth(environ={"CLAUDE_CONFIG_DIR": str(tmp_path)}, config_dir=config_dir)

        assert isinstance(result, ErrorResult)
        assert "ANTHROPIC_API_KEY" in result.error


@pytest.mark.parametrize(
    ("inline", "servers"),
    [
        (False, {}),
        (
            True,
            {
                "github_inline_comment": {
                    "command": "/py",
                    "args": ["-I", "-m", "dev10x.ci_review.inline_stub"],
                }
            },
        ),
    ],
)
def test_write_mcp_config(tmp_path: Path, inline: bool, servers: dict[str, Any]) -> None:
    path = write_mcp_config(run_dir=tmp_path, inline=inline, python="/py")

    assert json.loads(path.read_text(encoding="utf-8")) == {"mcpServers": servers}


def test_parse_stream_skips_noise() -> None:
    assert parse_stream(stdout='{"type": "a"}\nnot json\n[1]\n{"type": "b"}\n') == [
        {"type": "a"},
        {"type": "b"},
    ]


def test_node_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/opt/node/bin/node")

    assert runner.node_dir() == Path("/opt/node/bin")


def test_node_dir_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)

    assert runner.node_dir() is None


class TestRunClaude:
    @pytest.fixture
    def invocation(self, tmp_path: Path) -> Invocation:
        return Invocation(argv=["claude"], env={}, cwd=tmp_path)

    def _fake(
        self,
        *,
        monkeypatch: pytest.MonkeyPatch,
        returncode: int = 0,
        raises: Exception | None = None,
    ) -> None:
        def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            if raises is not None:
                raise raises
            return subprocess.CompletedProcess(
                args=args, returncode=returncode, stdout='{"type": "result"}\n', stderr="bad"
            )

        monkeypatch.setattr(runner.subprocess_utils, "run", fake_run)

    def test_writes_execution_file(
        self, monkeypatch: pytest.MonkeyPatch, invocation: Invocation, tmp_path: Path
    ) -> None:
        self._fake(monkeypatch=monkeypatch)

        result = run_claude(invocation=invocation, run_dir=tmp_path, timeout=5)

        assert result == SuccessResult(value=[{"type": "result"}])
        assert json.loads((tmp_path / "execution.json").read_text(encoding="utf-8")) == [
            {"type": "result"}
        ]

    def test_nonzero_exit_still_writes_execution(
        self, monkeypatch: pytest.MonkeyPatch, invocation: Invocation, tmp_path: Path
    ) -> None:
        self._fake(monkeypatch=monkeypatch, returncode=2)

        result = run_claude(invocation=invocation, run_dir=tmp_path, timeout=5)

        assert isinstance(result, ErrorResult)
        assert result.details == {"stderr": "bad"}
        assert (tmp_path / "execution.json").is_file()

    @pytest.mark.parametrize(
        ("raises", "message"),
        [
            (subprocess.TimeoutExpired(cmd="claude", timeout=5), "did not finish within 5s"),
            (FileNotFoundError("claude"), "could not start"),
        ],
        ids=["timeout", "missing"],
    )
    def test_process_failures(
        self,
        monkeypatch: pytest.MonkeyPatch,
        invocation: Invocation,
        tmp_path: Path,
        raises: Exception,
        message: str,
    ) -> None:
        self._fake(monkeypatch=monkeypatch, raises=raises)

        result = run_claude(invocation=invocation, run_dir=tmp_path, timeout=5)

        assert isinstance(result, ErrorResult)
        assert message in result.error
