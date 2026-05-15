from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

perm_mod = pytest.importorskip("dev10x.permission", reason="dev10x not installed")

MOD_PATH = "dev10x.skills.permission.update_paths"


class TestUpdatePathsScriptRoute:
    @pytest.mark.asyncio
    @patch("dev10x.permission.async_run", new_callable=AsyncMock)
    async def test_returns_output_on_success(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Updated 3 files",
            stderr="",
        )
        result = await perm_mod.update_paths()
        assert result["success"] is True
        assert "Updated 3 files" in result["output"]

    @pytest.mark.asyncio
    @patch("dev10x.permission.async_run", new_callable=AsyncMock)
    async def test_returns_error_on_failure(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Config not found",
        )
        result = await perm_mod.update_paths()
        assert "error" in result

    @pytest.mark.asyncio
    @patch("dev10x.permission.async_run", new_callable=AsyncMock)
    async def test_passes_script_flags(
        self,
        mock_run: AsyncMock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="OK",
            stderr="",
        )
        await perm_mod.update_paths(
            version="1.0.0",
            dry_run=True,
            init=True,
            quiet=True,
        )
        args_list = mock_run.call_args.kwargs["args"]
        assert "--version" in args_list
        assert "1.0.0" in args_list
        assert "--dry-run" in args_list
        assert "--init" in args_list
        assert "--quiet" in args_list


class TestUpdatePathsSubCommandRoute:
    @pytest.mark.asyncio
    @patch("dev10x.permission._run_sub_command")
    async def test_ensure_base_routes_to_sub_command(
        self,
        mock_sub: AsyncMock,
    ) -> None:
        mock_sub.return_value = {"success": True, "output": "Added 2 permissions"}
        result = await perm_mod.update_paths(ensure_base=True, dry_run=True)
        assert result["success"] is True
        mock_sub.assert_called_once_with(
            ensure_base=True,
            generalize=False,
            ensure_scripts=False,
            ensure_workspace=False,
            ensure_reads=False,
            dry_run=True,
            quiet=False,
        )

    @pytest.mark.asyncio
    @patch("dev10x.permission._run_sub_command")
    async def test_generalize_routes_to_sub_command(
        self,
        mock_sub: AsyncMock,
    ) -> None:
        mock_sub.return_value = {"success": True, "output": "Generalized 5 permissions"}
        result = await perm_mod.update_paths(generalize=True)
        assert result["success"] is True
        mock_sub.assert_called_once_with(
            ensure_base=False,
            generalize=True,
            ensure_scripts=False,
            ensure_workspace=False,
            ensure_reads=False,
            dry_run=False,
            quiet=False,
        )

    @pytest.mark.asyncio
    @patch("dev10x.permission._run_sub_command")
    async def test_ensure_scripts_routes_to_sub_command(
        self,
        mock_sub: AsyncMock,
    ) -> None:
        mock_sub.return_value = {"success": True, "output": "Added 3 script rules"}
        result = await perm_mod.update_paths(ensure_scripts=True)
        assert result["success"] is True
        mock_sub.assert_called_once_with(
            ensure_base=False,
            generalize=False,
            ensure_scripts=True,
            ensure_workspace=False,
            ensure_reads=False,
            dry_run=False,
            quiet=False,
        )

    @pytest.mark.asyncio
    @patch("dev10x.permission._run_sub_command")
    async def test_ensure_reads_routes_to_sub_command(
        self,
        mock_sub: AsyncMock,
    ) -> None:
        mock_sub.return_value = {"success": True, "output": "Added 12 Read rules"}
        result = await perm_mod.update_paths(ensure_reads=True)
        assert result["success"] is True
        mock_sub.assert_called_once_with(
            ensure_base=False,
            generalize=False,
            ensure_scripts=False,
            ensure_workspace=False,
            ensure_reads=True,
            dry_run=False,
            quiet=False,
        )

    @pytest.mark.asyncio
    @patch("dev10x.permission.async_run", new_callable=AsyncMock)
    @patch("dev10x.permission._run_sub_command")
    async def test_sub_command_flags_do_not_reach_script(
        self,
        mock_sub: AsyncMock,
        mock_run: AsyncMock,
    ) -> None:
        mock_sub.return_value = {"success": True, "output": "OK"}
        await perm_mod.update_paths(ensure_base=True, generalize=True)
        mock_run.assert_not_called()


class TestRunSubCommand:
    @pytest.fixture()
    def mock_mod(self):
        with (
            patch(f"{MOD_PATH}.find_config") as find_cfg,
            patch(f"{MOD_PATH}.load_config") as load_cfg,
            patch(f"{MOD_PATH}.find_settings_files") as find_sf,
        ):
            find_cfg.return_value = "/fake/config.yaml"
            load_cfg.return_value = {"roots": ["/fake"], "include_user_settings": True}
            find_sf.return_value = ["/fake/settings.json"]
            yield {
                "find_config": find_cfg,
                "load_config": load_cfg,
                "find_settings_files": find_sf,
            }

    @patch(
        f"{MOD_PATH}.ensure_base",
        return_value={"exit_code": 0, "messages": ["ok"], "errors": []},
    )
    def test_ensure_base_calls_underlying_function(
        self,
        mock_ensure: AsyncMock,
        mock_mod: dict,
    ) -> None:
        result = perm_mod._run_sub_command(ensure_base=True, dry_run=True)
        assert result["success"] is True
        mock_ensure.assert_called_once()

    @patch(
        f"{MOD_PATH}.generalize",
        return_value={"exit_code": 0, "messages": [], "errors": []},
    )
    def test_generalize_calls_underlying_function(
        self,
        mock_gen: AsyncMock,
        mock_mod: dict,
    ) -> None:
        result = perm_mod._run_sub_command(generalize=True)
        assert result["success"] is True
        mock_gen.assert_called_once()

    @patch(
        f"{MOD_PATH}.ensure_scripts",
        return_value={"exit_code": 0, "messages": [], "errors": []},
    )
    def test_ensure_scripts_calls_underlying_function(
        self,
        mock_scripts: AsyncMock,
        mock_mod: dict,
    ) -> None:
        result = perm_mod._run_sub_command(ensure_scripts=True)
        assert result["success"] is True
        mock_scripts.assert_called_once()

    @patch(
        f"{MOD_PATH}.ensure_reads",
        return_value={"exit_code": 0, "messages": [], "errors": []},
    )
    def test_ensure_reads_calls_underlying_function(
        self,
        mock_reads: AsyncMock,
        mock_mod: dict,
    ) -> None:
        result = perm_mod._run_sub_command(ensure_reads=True)
        assert result["success"] is True
        mock_reads.assert_called_once()

    @patch(
        f"{MOD_PATH}.ensure_base",
        return_value={
            "exit_code": 1,
            "messages": [],
            "errors": ["boom"],
        },
    )
    def test_returns_error_on_nonzero_exit(
        self,
        mock_ensure: AsyncMock,
        mock_mod: dict,
    ) -> None:
        result = perm_mod._run_sub_command(ensure_base=True)
        assert "error" in result
        assert result["error"] == "boom"

    @patch(
        f"{MOD_PATH}.generalize",
        return_value={"exit_code": 0, "messages": [], "errors": []},
    )
    @patch(
        f"{MOD_PATH}.ensure_base",
        return_value={"exit_code": 1, "messages": [], "errors": ["boom"]},
    )
    def test_skips_generalize_when_ensure_base_fails(
        self,
        mock_ensure: AsyncMock,
        mock_gen: AsyncMock,
        mock_mod: dict,
    ) -> None:
        result = perm_mod._run_sub_command(ensure_base=True, generalize=True)
        assert "error" in result
        mock_gen.assert_not_called()

    def test_does_not_capture_stdout(
        self,
        mock_mod: dict,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """MCP service must not redirect_stdout — helpers return structured data."""
        with patch(
            f"{MOD_PATH}.ensure_base",
            return_value={
                "exit_code": 0,
                "messages": ["Added 2 base permissions"],
                "errors": [],
            },
        ):
            result = perm_mod._run_sub_command(ensure_base=True)

        assert result["success"] is True
        assert "Added 2 base permissions" in result["output"]
        # Helper did not print to real stdout — capsys captures nothing.
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_error_path_surfaces_helper_errors(
        self,
        mock_mod: dict,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Error envelope carries structured errors list — no stdout capture."""
        with patch(
            f"{MOD_PATH}.ensure_scripts",
            return_value={
                "exit_code": 1,
                "messages": [],
                "errors": ["ERROR: No versions found in /fake/cache"],
            },
        ):
            result = perm_mod._run_sub_command(ensure_scripts=True)

        assert "error" in result
        assert "No versions found" in result["error"]
        assert result["errors"] == ["ERROR: No versions found in /fake/cache"]
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_returns_error_when_no_settings_files(self) -> None:
        with (
            patch(f"{MOD_PATH}.find_config") as find_cfg,
            patch(f"{MOD_PATH}.load_config") as load_cfg,
            patch(f"{MOD_PATH}.find_settings_files") as find_sf,
        ):
            find_cfg.return_value = "/fake/config.yaml"
            load_cfg.return_value = {"roots": []}
            find_sf.return_value = []
            result = perm_mod._run_sub_command(ensure_base=True)
            assert result["error"] == "No settings files found."
