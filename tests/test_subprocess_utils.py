"""Tests for dev10x.subprocess_utils."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev10x.subprocess_utils import (
    get_plugin_root,
    parse_json_output,
    parse_key_value_output,
    resolve_script_path,
    run_script,
)


class TestGetPluginRoot:
    def test_returns_path_two_levels_above_lib(self) -> None:
        result = get_plugin_root()

        assert isinstance(result, Path)
        assert result.name != "lib"
        assert (result / "servers").is_dir()


class TestResolveScriptPath:
    @pytest.fixture()
    def fake_plugin_source(self, tmp_path: Path) -> Path:
        """A directory that looks like a plugin source repo."""
        marker_dir = tmp_path / ".claude-plugin"
        marker_dir.mkdir()
        (marker_dir / "plugin.json").write_text("{}")
        return tmp_path

    def test_prefers_working_dir_when_script_exists_locally(
        self,
        fake_plugin_source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        local_script = fake_plugin_source / "bin" / "mktmp.sh"
        local_script.parent.mkdir(parents=True)
        local_script.write_text("#!/bin/sh\n")
        monkeypatch.chdir(fake_plugin_source)

        resolved = resolve_script_path("bin/mktmp.sh")

        assert resolved == local_script

    def test_falls_back_to_cached_when_script_missing_locally(
        self,
        fake_plugin_source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # plugin.json marker exists but the requested script does not
        monkeypatch.chdir(fake_plugin_source)

        resolved = resolve_script_path("bin/mktmp.sh")

        assert resolved == get_plugin_root() / "bin/mktmp.sh"

    def test_falls_back_to_cached_when_cwd_not_plugin_source(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # tmp_path has no .claude-plugin/ — looks like a regular project
        monkeypatch.chdir(tmp_path)

        resolved = resolve_script_path("bin/mktmp.sh")

        assert resolved == get_plugin_root() / "bin/mktmp.sh"

    def test_walks_up_to_find_plugin_marker(
        self,
        fake_plugin_source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CWD is a subdir of the plugin source — marker is in an ancestor."""
        local_script = fake_plugin_source / "skills" / "x" / "run.sh"
        local_script.parent.mkdir(parents=True)
        local_script.write_text("#!/bin/sh\n")
        nested = fake_plugin_source / "subdir" / "deep"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        resolved = resolve_script_path("skills/x/run.sh")

        assert resolved == local_script


class TestRunScript:
    def test_returns_sentinel_for_missing_script(self) -> None:
        result = run_script("nonexistent/script.sh")

        assert result.returncode == -1
        assert result.stdout == ""
        assert "Script not found" in result.stderr
        assert "nonexistent/script.sh" in result.stderr

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_calls_subprocess_with_full_path(
        self,
        mock_run: patch,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        plugin_root = get_plugin_root()
        script = "tests/mcp/conftest.py"

        run_script(script, "arg1", "arg2")

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == str(plugin_root / script)
        assert cmd[1] == "arg1"
        assert cmd[2] == "arg2"

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_passes_env_vars(
        self,
        mock_run: patch,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        script = "tests/mcp/conftest.py"

        run_script(script, env_vars={"MY_VAR": "my_value"})

        call_args = mock_run.call_args
        env = call_args[1]["env"]
        assert env["MY_VAR"] == "my_value"

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_captures_output_as_text(
        self,
        mock_run: patch,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="output",
            stderr="",
        )
        script = "tests/mcp/conftest.py"

        run_script(script)

        call_args = mock_run.call_args
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is False


class TestRun:
    """GH-979: the sync run() chokepoint defaults cwd to the effective CWD."""

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_explicit_cwd_wins(self, mock_run: patch) -> None:
        from dev10x.subprocess_utils import run

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        run(["git", "status"], cwd="/explicit")

        assert mock_run.call_args[1]["cwd"] == "/explicit"

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_defaults_to_effective_cwd_when_bound(self, mock_run: patch) -> None:
        from dev10x.subprocess_utils import run, use_cwd

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with use_cwd("/bound"):
            run(["git", "status"])

        assert mock_run.call_args[1]["cwd"] == "/bound"

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_cwd_is_none_when_unbound(self, mock_run: patch) -> None:
        from dev10x.subprocess_utils import run

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        run(["git", "status"])

        assert mock_run.call_args[1]["cwd"] is None

    @patch("dev10x.subprocess_utils.subprocess.run")
    def test_passes_through_other_kwargs(self, mock_run: patch) -> None:
        from dev10x.subprocess_utils import run

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        run(["ruff", "format", "x.py"], check=False, capture_output=True, text=True)

        kwargs = mock_run.call_args[1]
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True

    def test_runs_real_command(self) -> None:
        from dev10x.subprocess_utils import run

        result = run(["echo", "hi"], capture_output=True, text=True)

        assert result.returncode == 0
        assert result.stdout.strip() == "hi"


class TestParseKeyValueOutput:
    def test_parses_single_pair(self) -> None:
        result = parse_key_value_output("KEY=value")

        assert result == {"KEY": "value"}

    def test_parses_multiple_pairs(self) -> None:
        text = "TRACKER=github\nTICKET_ID=GH-15\nFIXES_URL=http://example.com"

        result = parse_key_value_output(text)

        assert result == {
            "TRACKER": "github",
            "TICKET_ID": "GH-15",
            "FIXES_URL": "http://example.com",
        }

    def test_skips_empty_lines(self) -> None:
        text = "KEY1=val1\n\nKEY2=val2\n"

        result = parse_key_value_output(text)

        assert result == {"KEY1": "val1", "KEY2": "val2"}

    def test_skips_lines_without_equals(self) -> None:
        text = "KEY=value\nno-equals-here\nKEY2=val2"

        result = parse_key_value_output(text)

        assert result == {"KEY": "value", "KEY2": "val2"}

    def test_handles_equals_in_value(self) -> None:
        text = "URL=http://example.com?a=1&b=2"

        result = parse_key_value_output(text)

        assert result == {"URL": "http://example.com?a=1&b=2"}

    def test_returns_empty_dict_for_empty_input(self) -> None:
        result = parse_key_value_output("")

        assert result == {}


class TestParseJsonOutput:
    def test_parses_valid_json(self) -> None:
        data = {"key": "value", "count": 42}

        result = parse_json_output(json.dumps(data))

        assert result == data

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            parse_json_output("not json")


class TestAsyncRun:
    @pytest.fixture
    def sut(self):
        from dev10x.subprocess_utils import async_run

        return async_run

    @pytest.mark.asyncio
    async def test_runs_command_and_captures_output(self, sut) -> None:
        result = await sut(args=["echo", "hello"])

        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    @pytest.mark.asyncio
    async def test_captures_stderr(self, sut) -> None:
        result = await sut(args=["sh", "-c", "echo err >&2"])

        assert result.stderr.strip() == "err"

    @pytest.mark.asyncio
    async def test_returns_nonzero_on_failure(self, sut) -> None:
        result = await sut(args=["false"])

        assert result.returncode != 0

    @pytest.mark.asyncio
    async def test_timeout_returns_negative_returncode(self, sut) -> None:
        result = await sut(args=["sleep", "10"], timeout=0.1)

        assert result.returncode == -1
        assert "timed out" in result.stderr.lower()


class TestAsyncRunScript:
    @pytest.fixture
    def sut(self):
        from dev10x.subprocess_utils import async_run_script

        return async_run_script

    @pytest.mark.asyncio
    async def test_returns_sentinel_for_missing_script(self, sut) -> None:
        result = await sut("nonexistent/script.sh")

        assert result.returncode == -1
        assert result.stdout == ""
        assert "Script not found" in result.stderr
        assert "nonexistent/script.sh" in result.stderr

    @pytest.mark.asyncio
    async def test_runs_existing_script(self, sut) -> None:
        result = await sut("bin/mktmp.sh", "test-ns", "test-prefix", ".txt")

        assert result.returncode == 0
        assert result.stdout.strip().startswith("/tmp/")


class TestEffectiveCwd:
    """GH-979: subprocess calls must honor the per-call effective CWD."""

    @pytest.fixture
    def two_repos(self, tmp_path: Path) -> tuple[Path, Path]:
        main = tmp_path / "main"
        worktree = tmp_path / "wt"
        for d in (main, worktree):
            d.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            (d / "marker.txt").write_text(d.name)
            subprocess.run(["git", "add", "."], cwd=d, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=t@t",
                    "-c",
                    "user.name=T",
                    "commit",
                    "-qm",
                    f"init {d.name}",
                ],
                cwd=d,
                check=True,
            )
            subprocess.run(["git", "checkout", "-qb", f"{d.name}-branch"], cwd=d, check=True)
        return main, worktree

    @pytest.mark.asyncio
    async def test_async_run_explicit_cwd_overrides_process_cwd(
        self,
        two_repos: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.subprocess_utils import async_run

        main, worktree = two_repos
        monkeypatch.chdir(main)

        result = await async_run(
            args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(worktree),
        )

        assert result.stdout.strip() == "wt-branch"

    @pytest.mark.asyncio
    async def test_async_run_uses_context_var_when_cwd_omitted(
        self,
        two_repos: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.subprocess_utils import async_run, use_cwd

        main, worktree = two_repos
        monkeypatch.chdir(main)

        with use_cwd(str(worktree)):
            result = await async_run(args=["git", "rev-parse", "--abbrev-ref", "HEAD"])

        assert result.stdout.strip() == "wt-branch"

    @pytest.mark.asyncio
    async def test_use_cwd_does_not_leak_after_block(
        self,
        two_repos: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.subprocess_utils import async_run, effective_cwd, use_cwd

        main, worktree = two_repos
        monkeypatch.chdir(main)

        with use_cwd(str(worktree)):
            assert effective_cwd() == str(worktree)

        assert effective_cwd() is None

        result = await async_run(args=["git", "rev-parse", "--abbrev-ref", "HEAD"])
        assert result.stdout.strip() == "main-branch"

    def test_use_cwd_with_none_is_a_noop(self) -> None:
        from dev10x.subprocess_utils import effective_cwd, use_cwd

        with use_cwd("/some/path"):
            with use_cwd(None):
                assert effective_cwd() == "/some/path"

    def test_run_script_passes_cwd_to_subprocess(
        self,
        tmp_path: Path,
    ) -> None:
        from dev10x.subprocess_utils import run_script

        with patch("dev10x.subprocess_utils.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            run_script("bin/mktmp.sh", "x", "y", cwd=str(tmp_path))

        assert mock_run.call_args[1]["cwd"] == str(tmp_path)


class TestGitContextHonorsCwd:
    """GH-979: GitContext must not lock in the first CWD it sees."""

    @pytest.fixture
    def two_repos(self, tmp_path: Path) -> tuple[Path, Path]:
        a = tmp_path / "a"
        b = tmp_path / "b"
        for d in (a, b):
            d.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            (d / "f.txt").write_text(d.name)
            subprocess.run(["git", "add", "."], cwd=d, check=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "init"],
                cwd=d,
                check=True,
            )
        return a, b

    def test_explicit_cwd_overrides_process_cwd(
        self,
        two_repos: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.domain.git_context import GitContext

        a, b = two_repos
        monkeypatch.chdir(a)

        ctx = GitContext(cwd=str(b))

        # Resolve symlinks (macOS /var → /private/var) before comparing
        assert Path(ctx.toplevel).resolve() == b.resolve()

    def test_fresh_instances_do_not_share_cache(
        self,
        two_repos: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.domain.git_context import GitContext

        a, b = two_repos
        monkeypatch.chdir(a)
        first = GitContext()
        assert Path(first.toplevel).resolve() == a.resolve()

        monkeypatch.chdir(b)
        second = GitContext()
        assert Path(second.toplevel).resolve() == b.resolve()

    def test_context_var_drives_default_cwd(
        self,
        two_repos: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from dev10x.domain.git_context import GitContext
        from dev10x.subprocess_utils import use_cwd

        a, b = two_repos
        monkeypatch.chdir(a)

        with use_cwd(str(b)):
            ctx = GitContext()
            assert Path(ctx.toplevel).resolve() == b.resolve()
