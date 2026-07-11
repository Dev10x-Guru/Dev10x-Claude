"""Tests for the shared PluginLoader (#844)."""

from __future__ import annotations

import pytest

from dev10x.domain.common.plugin_loader import PluginLoader


class TestResolve:
    def test_returns_marker_passing_type_gate(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        assert loader.resolve(module_path="sys", marker="maxsize") > 0

    def test_missing_marker_is_none(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        assert loader.resolve(module_path="sys", marker="nonexistent_attr") is None

    def test_wrong_type_is_none(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        # sys.path is a list, not an int — dropped by the type gate.
        assert loader.resolve(module_path="sys", marker="path") is None

    def test_transform_runs_before_type_gate(self) -> None:
        loader: PluginLoader[str] = PluginLoader(protocol=str, transform=str)

        assert loader.resolve(module_path="sys", marker="maxsize") == str(
            __import__("sys").maxsize
        )


class TestRequire:
    def test_returns_marker_passing_type_gate(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        assert loader.require(module_path="sys", marker="maxsize") > 0

    def test_missing_marker_raises_attribute_error(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        with pytest.raises(AttributeError, match="nonexistent_attr"):
            loader.require(module_path="sys", marker="nonexistent_attr")

    def test_wrong_type_raises_type_error(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        with pytest.raises(TypeError, match="not a int"):
            loader.require(module_path="sys", marker="path")


class TestCollect:
    def test_drops_missing_and_mistyped_sources(self) -> None:
        loader: PluginLoader[int] = PluginLoader(protocol=int)

        result = loader.collect(
            [
                ("sys", "maxsize"),
                ("sys", "nonexistent_attr"),
                ("os", "getpid"),  # a function, not an int
            ]
        )

        assert result == [__import__("sys").maxsize]
