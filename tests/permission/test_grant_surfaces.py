"""MCP, adapter and CLI surfaces for triage-then-grant (GH-1676)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from dev10x.domain.common.result import ErrorResult, SuccessResult, ok
from dev10x.permission.service import PermissionContext

from dev10x import permission as perm_mod
from dev10x.commands.permission import permission as permission_cli
from dev10x.core.mcp import utility_tools
from dev10x.skills.permission import catalog_write

CONTEXT = "dev10x.permission.load_permission_context"
CLI_CONTEXT = "dev10x.commands.permission.load_permission_context"


@pytest.fixture(autouse=True)
def _untracked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_write, "_is_git_tracked", lambda _path: False)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    return path


@pytest.fixture
def settings_file(workdir: Path) -> Path:
    path = workdir / ".claude" / "settings.local.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"permissions": {"allow": []}}))
    return path


@pytest.fixture
def context(settings_file: Path) -> PermissionContext:
    return PermissionContext(
        config_path=Path("/fake/projects.yaml"),
        config={"base_denies": ["Bash(pnpm deploy:*)"]},
        settings_files=[settings_file],
    )


@pytest.fixture
def empty_context() -> PermissionContext:
    return PermissionContext(
        config_path=Path("/fake/projects.yaml"),
        config={},
        settings_files=[],
    )


def _allow(path: Path) -> list[str]:
    return json.loads(path.read_text())["permissions"]["allow"]


class TestAdapter:
    @pytest.mark.asyncio
    async def test_triage_returns_wire_dict(
        self, context: PermissionContext, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            result = await perm_mod.triage(target="make test", working_dirs=[str(workdir)])
        assert isinstance(result, SuccessResult)
        assert (result.value["verdict"], result.value["rule"]) == ("grant", "Bash(make:*)")

    @pytest.mark.asyncio
    async def test_triage_reads_catalog_denies(
        self, context: PermissionContext, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            result = await perm_mod.triage(target="pnpm deploy", working_dirs=[str(workdir)])
        assert isinstance(result, SuccessResult)
        assert result.value["verdict"] == "denied"

    @pytest.mark.asyncio
    async def test_triage_defaults_working_dirs_to_cwd(
        self, context: PermissionContext, workdir: Path
    ) -> None:
        with (
            patch(CONTEXT, return_value=ok(context)),
            patch("dev10x.subprocess_utils.effective_cwd", return_value=str(workdir)),
        ):
            result = await perm_mod.triage(target=f"rg x {workdir}/src")
        assert isinstance(result, SuccessResult)
        assert result.value["verdict"] == "grant"

    @pytest.mark.asyncio
    async def test_grant_writes_settings(
        self, context: PermissionContext, settings_file: Path, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            await perm_mod.grant(
                target="make test",
                rule="Bash(make:*)",
                working_dirs=[str(workdir)],
            )
        assert _allow(settings_file) == ["Bash(make:*)"]

    @pytest.mark.asyncio
    async def test_grant_refuses_unconfirmed_rule(
        self, context: PermissionContext, settings_file: Path, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            result = await perm_mod.grant(
                target="make test",
                rule="Bash(make test:*)",
                working_dirs=[str(workdir)],
            )
        assert isinstance(result, ErrorResult)
        assert (result.details["triage"]["rule"], _allow(settings_file)) == ("Bash(make:*)", [])

    @pytest.mark.asyncio
    async def test_grant_errors_without_settings_files(
        self, empty_context: PermissionContext
    ) -> None:
        with patch(CONTEXT, return_value=ok(empty_context)):
            result = await perm_mod.grant(target="make test", rule="Bash(make:*)")
        assert isinstance(result, ErrorResult)
        assert "No settings files" in result.error

    @pytest.mark.parametrize(
        "operation",
        [
            lambda: perm_mod.triage(target="make test", working_dirs=["repo"]),
            lambda: perm_mod.grant(target="make test", rule="Bash(make:*)", working_dirs=["."]),
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_relative_working_dirs(
        self, operation: object, context: PermissionContext
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            result = await operation()  # type: ignore[operator]
        assert isinstance(result, ErrorResult)
        assert "must be absolute" in result.error

    @pytest.mark.parametrize(
        "operation",
        [
            lambda: perm_mod.triage(target="make test"),
            lambda: perm_mod.grant(target="make test", rule="Bash(make:*)"),
        ],
    )
    @pytest.mark.asyncio
    async def test_propagates_context_error(self, operation: object) -> None:
        with patch(CONTEXT, return_value=ErrorResult(error="No config found.")):
            result = await operation()  # type: ignore[operator]
        assert isinstance(result, ErrorResult)
        assert result.error == "No config found."

    def test_catalog_denies_include_configured_denies(self) -> None:
        assert "Bash(pnpm deploy:*)" in perm_mod.catalog_denies(
            config={"base_denies": ["Bash(pnpm deploy:*)"]}
        )


class TestMcpTools:
    @pytest.mark.asyncio
    async def test_triage_tool_returns_verdict(
        self, context: PermissionContext, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            payload = await utility_tools.permission_triage(
                target="git status && git log",
                cwd=str(workdir),
            )
        assert payload["verdict"] == "normalize"

    @pytest.mark.asyncio
    async def test_grant_tool_dry_run_reports_without_writing(
        self, context: PermissionContext, settings_file: Path, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            payload = await utility_tools.permission_grant(
                target="make test",
                rule="Bash(make:*)",
                dry_run=True,
                cwd=str(workdir),
            )
        assert (payload["granted"], _allow(settings_file)) == ([str(settings_file)], [])

    @pytest.mark.asyncio
    async def test_grant_tool_refusal_carries_triage(
        self, context: PermissionContext, workdir: Path
    ) -> None:
        with patch(CONTEXT, return_value=ok(context)):
            payload = await utility_tools.permission_grant(
                target="cat ~/.ssh/id_rsa",
                rule="Bash(cat:*)",
                cwd=str(workdir),
            )
        assert payload["triage"]["verdict"] == "refuse-sensitive"


class TestCli:
    @pytest.mark.parametrize(
        ("target", "exit_code", "verdict_line"),
        [
            ("make test", 0, "Verdict: grant"),
            ("git status && git log", 1, "Verdict: normalize"),
        ],
    )
    def test_triage_exit_code_tracks_grant(
        self,
        context: PermissionContext,
        workdir: Path,
        target: str,
        exit_code: int,
        verdict_line: str,
    ) -> None:
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["triage", target, "--working-dir", str(workdir)],
            )
        assert (result.exit_code, verdict_line in result.output) == (exit_code, True)

    def test_triage_lists_files_missing_rule(
        self, context: PermissionContext, settings_file: Path, workdir: Path
    ) -> None:
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["triage", "make test", "--working-dir", str(workdir)],
            )
        assert f"missing in {settings_file}" in result.output

    def test_triage_defaults_working_dir_to_cwd(
        self, context: PermissionContext, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(workdir)
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(permission_cli, ["triage", "rg x /etc/hosts"])
        assert "additionalDirectories" in result.output

    def test_grant_writes_and_reports(
        self, context: PermissionContext, settings_file: Path, workdir: Path
    ) -> None:
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["grant", "make test", "--working-dir", str(workdir)],
            )
        assert "Granted Bash(make:*) in 1 file(s)." in result.output
        assert _allow(settings_file) == ["Bash(make:*)"]

    def test_grant_dry_run_says_would(self, context: PermissionContext, workdir: Path) -> None:
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["grant", "make test", "--working-dir", str(workdir), "--dry-run"],
            )
        assert "Would grant Bash(make:*) in 1 file(s)." in result.output

    def test_grant_refusal_exits_nonzero_with_advice(
        self, context: PermissionContext, workdir: Path
    ) -> None:
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["grant", "git status && git log", "--working-dir", str(workdir)],
            )
        assert result.exit_code == 1
        assert "Split the chain" in result.output

    def test_grant_without_settings_files_fails_loudly(
        self, empty_context: PermissionContext
    ) -> None:
        with patch(CLI_CONTEXT, return_value=ok(empty_context)):
            result = CliRunner().invoke(permission_cli, ["grant", "make test"])
        assert (result.exit_code, "No settings files found." in result.output) == (1, True)

    def test_relative_working_dir_is_resolved(
        self, context: PermissionContext, workdir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(workdir)
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["triage", f"rg x {workdir}/src", "--working-dir", "."],
            )
        assert "Verdict: grant" in result.output

    def test_triage_lists_unreadable_files(
        self, context: PermissionContext, settings_file: Path, workdir: Path
    ) -> None:
        settings_file.write_text("{not json")
        with patch(CLI_CONTEXT, return_value=ok(context)):
            result = CliRunner().invoke(
                permission_cli,
                ["triage", "make test", "--working-dir", str(workdir)],
            )
        assert f"unreadable {settings_file}" in result.output
