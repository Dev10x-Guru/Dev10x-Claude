"""Tests for dev10x.permission MCP module (GH-108 Result[T] migration).

Covers the structured-error contract for update_paths — both the
sub-command branch and the in-process version-bump branch — so the
boundary handler in server_cli.py can rely on .to_dict() to render
the envelope at the MCP edge.

GH-269: the version-bump branch used to shell out to
``skills/upgrade-cleanup/scripts/update-paths.py``. That shim
script was retired; the branch now runs in-process against
``dev10x.skills.permission.update_paths`` (the same module the
CLI uses) so plugin upgrades stop rotting the allow-rule.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

perm_mod = pytest.importorskip("dev10x.permission", reason="dev10x not installed")
from dev10x.domain.common.result import ErrorResult, SuccessResult  # noqa: E402

MOD = "dev10x.skills.permission.update_paths"


class TestUpdatePathsInProcess:
    @pytest.mark.asyncio
    async def test_returns_success_when_files_already_up_to_date(self) -> None:
        with (
            patch(f"{MOD}.find_config", return_value=Path("/fake/config.yaml")),
            patch(
                f"{MOD}.load_config",
                return_value={
                    "roots": ["/fake"],
                    "include_user_settings": True,
                    "plugin_cache": "/fake/cache",
                },
            ),
            patch(f"{MOD}.find_settings_files", return_value=[Path("/fake/settings.json")]),
            patch(f"{MOD}.detect_latest_version", return_value="1.0.0"),
            patch(f"{MOD}.extract_cache_publisher", return_value="Dev10x-Guru"),
            patch(f"{MOD}.update_file", return_value=(0, [])),
        ):
            result = await perm_mod.update_paths()

        assert isinstance(result, SuccessResult)
        assert result.value["success"] is True
        assert result.value["total_changes"] == 0
        assert "All files already up to date" in result.value["output"]

    @pytest.mark.asyncio
    async def test_returns_structured_error_when_no_versions_detected(self) -> None:
        with (
            patch(f"{MOD}.find_config", return_value=Path("/fake/config.yaml")),
            patch(
                f"{MOD}.load_config",
                return_value={
                    "roots": ["/fake"],
                    "include_user_settings": True,
                    "plugin_cache": "/fake/cache",
                },
            ),
            patch(f"{MOD}.find_settings_files", return_value=[Path("/fake/settings.json")]),
            patch(f"{MOD}.detect_latest_version", return_value=None),
        ):
            result = await perm_mod.update_paths()

        assert isinstance(result, ErrorResult)
        assert "No versions found" in result.error
        assert result.to_dict() == {"error": result.error}

    @pytest.mark.asyncio
    async def test_init_is_routed_back_to_cli(self) -> None:
        """``init`` requires interactive file copies — MCP rejects it."""

        result = await perm_mod.update_paths(init=True)

        assert isinstance(result, ErrorResult)
        assert "uvx dev10x permission update-paths --init" in result.error


class TestUpdatePathsSubCommand:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_settings_files(self) -> None:
        with (
            patch("dev10x.skills.permission.update_paths.find_config"),
            patch(
                "dev10x.skills.permission.update_paths.load_config",
                return_value={"roots": [], "include_user_settings": False},
            ),
            patch(
                "dev10x.skills.permission.update_paths.find_settings_files",
                return_value=[],
            ),
        ):
            result = await perm_mod.update_paths(ensure_base=True)
        assert isinstance(result, ErrorResult)
        assert "No settings files" in result.error
