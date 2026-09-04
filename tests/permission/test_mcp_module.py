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
from dev10x.domain.common.result import ErrorResult, SuccessResult, ok  # noqa: E402

MOD = "dev10x.skills.permission.update_paths"


class TestUpdatePathsInProcess:
    @pytest.mark.asyncio
    async def test_returns_success_when_files_already_up_to_date(self) -> None:
        with (
            patch(f"{MOD}.find_config", return_value=ok(Path("/fake/config.yaml"))),
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
            patch(f"{MOD}.find_config", return_value=ok(Path("/fake/config.yaml"))),
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
        assert "uvx dev10x permission init" in result.error


class TestUpdatePathsInProcessMissingConfig:
    @pytest.mark.asyncio
    async def test_propagates_error_when_config_missing(self) -> None:
        """GH-532: a missing config returns ErrorResult instead of sys.exit."""
        missing = ErrorResult(error="No config found.")
        with patch(f"{MOD}.find_config", return_value=missing):
            result = await perm_mod.update_paths()

        assert result is missing

    @pytest.mark.asyncio
    async def test_sub_command_propagates_error_when_config_missing(self) -> None:
        missing = ErrorResult(error="No config found.")
        with patch(f"{MOD}.find_config", return_value=missing):
            result = await perm_mod.update_paths(ensure_base=True)

        assert result is missing


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


def _resolved_context(*, settings_files: list[Path]) -> object:
    return (
        patch(f"{MOD}.find_config", return_value=ok(Path("/fake/config.yaml"))),
        patch(
            f"{MOD}.load_config",
            return_value={
                "roots": ["/fake"],
                "include_user_settings": True,
                "plugin_cache": "/fake/cache",
            },
        ),
        patch(f"{MOD}.find_settings_files", return_value=settings_files),
    )


class TestCatalogGap:
    """GH-1175: the coverage check reachable without a Bash allow rule."""

    @pytest.mark.asyncio
    async def test_clean_when_nothing_is_missing(self) -> None:
        find_config, load_config, find_files = _resolved_context(
            settings_files=[Path("/fake/settings.json")]
        )
        with (
            find_config,
            load_config,
            find_files,
            patch(
                f"{MOD}.catalog_gap",
                return_value={
                    "exit_code": 0,
                    "messages": ["Catalog: 348 allow / 16 deny rules"],
                    "errors": [],
                    "total_added": 0,
                    "files_changed": 1,
                },
            ),
        ):
            result = await perm_mod.catalog_gap()

        assert isinstance(result, SuccessResult)
        assert result.value["clean"] is True
        assert result.value["total_missing"] == 0
        assert result.value["files_checked"] == 1
        assert result.value["messages"]

    @pytest.mark.asyncio
    async def test_reports_the_gap_rather_than_erroring(self) -> None:
        # A propagation gap is a finding, not an MCP-level failure — the
        # caller reads total_missing and routes on it (Step 3a).
        find_config, load_config, find_files = _resolved_context(
            settings_files=[Path("/a.json"), Path("/b.json")]
        )
        with (
            find_config,
            load_config,
            find_files,
            patch(
                f"{MOD}.catalog_gap",
                return_value={
                    "exit_code": 1,
                    "messages": ["/a.json — 137 missing allow"],
                    "errors": [],
                    "total_added": 137,
                    "files_changed": 2,
                },
            ),
        ):
            result = await perm_mod.catalog_gap(verbose=True)

        assert isinstance(result, SuccessResult)
        assert result.value["clean"] is False
        assert result.value["total_missing"] == 137
        assert result.value["files_checked"] == 2

    @pytest.mark.asyncio
    async def test_returns_error_when_no_settings_files(self) -> None:
        find_config, load_config, find_files = _resolved_context(settings_files=[])
        with find_config, load_config, find_files:
            result = await perm_mod.catalog_gap()

        assert isinstance(result, ErrorResult)
        assert "No settings files" in result.error

    @pytest.mark.asyncio
    async def test_propagates_a_context_resolution_error(self) -> None:
        with patch(
            "dev10x.permission.load_permission_context",
            return_value=ErrorResult(error="No config found."),
        ):
            result = await perm_mod.catalog_gap()

        assert isinstance(result, ErrorResult)
        assert "No config found." in result.error
