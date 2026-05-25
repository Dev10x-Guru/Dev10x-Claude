from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, ok

perm_mod = pytest.importorskip("dev10x.permission", reason="dev10x not installed")

MOD_PATH = "dev10x.skills.permission.update_paths"


class TestUpdatePathsInProcessRoute:
    """GH-269: the version-bump branch runs in-process.

    The retired ``skills/upgrade-cleanup/scripts/update-paths.py`` shim
    no longer exists, so there is no subprocess to mock. The tests below
    patch the underlying ``update_paths`` module functions instead.
    """

    @staticmethod
    def _stub_config():
        return {
            "roots": ["/fake"],
            "include_user_settings": True,
            "plugin_cache": "/fake/cache",
        }

    @pytest.mark.asyncio
    async def test_returns_success_with_change_summary(self) -> None:
        with (
            patch(f"{MOD_PATH}.find_config", return_value=Path("/fake/config.yaml")),
            patch(f"{MOD_PATH}.load_config", return_value=self._stub_config()),
            patch(f"{MOD_PATH}.find_settings_files", return_value=[Path("/fake/settings.json")]),
            patch(f"{MOD_PATH}.detect_latest_version", return_value="1.0.0"),
            patch(f"{MOD_PATH}.extract_cache_publisher", return_value="Dev10x-Guru"),
            patch(f"{MOD_PATH}.update_file", return_value=(3, ["  0.9 -> 1.0.0 (3)"])),
        ):
            result = await perm_mod.update_paths()

        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
        assert result.value["total_changes"] == 3
        assert result.value["files_changed"] == 1
        assert "Updated 3 paths in 1 files" in result.value["output"]

    @pytest.mark.asyncio
    async def test_returns_error_when_cache_is_empty(self) -> None:
        with (
            patch(f"{MOD_PATH}.find_config", return_value=Path("/fake/config.yaml")),
            patch(f"{MOD_PATH}.load_config", return_value=self._stub_config()),
            patch(f"{MOD_PATH}.find_settings_files", return_value=[Path("/fake/settings.json")]),
            patch(f"{MOD_PATH}.detect_latest_version", return_value=None),
        ):
            result = await perm_mod.update_paths()

        assert isinstance(result, ErrorResult)
        assert "No versions found" in result.error

    @pytest.mark.asyncio
    async def test_dry_run_passes_through_to_update_file(self) -> None:
        with (
            patch(f"{MOD_PATH}.find_config", return_value=Path("/fake/config.yaml")),
            patch(f"{MOD_PATH}.load_config", return_value=self._stub_config()),
            patch(f"{MOD_PATH}.find_settings_files", return_value=[Path("/fake/settings.json")]),
            patch(f"{MOD_PATH}.detect_latest_version", return_value="1.0.0"),
            patch(f"{MOD_PATH}.extract_cache_publisher", return_value=None),
            patch(f"{MOD_PATH}.update_file", return_value=(2, [])) as mock_update,
        ):
            result = await perm_mod.update_paths(dry_run=True, version="1.0.0")

        assert isinstance(result, SuccessResult)
        assert "Would update" in result.value["output"]
        assert mock_update.call_args.kwargs["dry_run"] is True

    @pytest.mark.asyncio
    async def test_init_is_rejected_with_pointer_to_cli(self) -> None:
        result = await perm_mod.update_paths(init=True)

        assert isinstance(result, ErrorResult)
        assert "uvx dev10x permission update-paths --init" in result.error


class TestUpdatePathsSubCommandRoute:
    @pytest.mark.asyncio
    @patch("dev10x.permission._run_sub_command")
    async def test_ensure_base_routes_to_sub_command(
        self,
        mock_sub: AsyncMock,
    ) -> None:
        mock_sub.return_value = ok({"success": True, "output": "Added 2 permissions"})
        result = await perm_mod.update_paths(ensure_base=True, dry_run=True)
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        mock_sub.return_value = ok({"success": True, "output": "Generalized 5 permissions"})
        result = await perm_mod.update_paths(generalize=True)
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        mock_sub.return_value = ok({"success": True, "output": "Added 3 script rules"})
        result = await perm_mod.update_paths(ensure_scripts=True)
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        mock_sub.return_value = ok({"success": True, "output": "Added 12 Read rules"})
        result = await perm_mod.update_paths(ensure_reads=True)
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
    @patch("dev10x.permission._run_update_paths")
    @patch("dev10x.permission._run_sub_command")
    async def test_sub_command_flags_skip_version_bump(
        self,
        mock_sub: AsyncMock,
        mock_run_update: AsyncMock,
    ) -> None:
        """Sub-command flags (ensure_base, generalize, …) must NOT also
        trigger the in-process version-bump path."""

        mock_sub.return_value = ok({"success": True, "output": "OK"})
        await perm_mod.update_paths(ensure_base=True, generalize=True)
        mock_run_update.assert_not_called()


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
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
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
        assert isinstance(result, ErrorResult)
        assert result.error == "boom"

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
        assert isinstance(result, ErrorResult)
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

        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
        assert "Added 2 base permissions" in result.value["output"]
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

        assert isinstance(result, ErrorResult)
        assert "No versions found" in result.error
        assert result.details["errors"] == ["ERROR: No versions found in /fake/cache"]
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
            assert isinstance(result, ErrorResult)
            assert result.error == "No settings files found."
