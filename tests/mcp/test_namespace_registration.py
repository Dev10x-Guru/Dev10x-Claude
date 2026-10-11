"""Per-namespace MCP registration (ADR-0034 Stage A2, GH-1549)."""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest
from mcp.server.fastmcp import FastMCP

from dev10x.core.mcp.registry import ForeignServerError, import_tool_modules
from dev10x.mcp import server_cli
from dev10x.mcp._app import server as cli_app

REGISTRATIONS = [f"dev10x.{namespace}.mcp.registration" for namespace in server_cli.CLI_NAMESPACES]


@pytest.fixture
def foreign_server() -> FastMCP:
    return FastMCP(name="foreign")


class TestImportToolModules:
    def test_imports_each_named_module(self) -> None:
        modules = import_tool_modules(server=cli_app, modules=("dev10x.comm.mcp.slack_tools",))

        assert modules == (importlib.import_module("dev10x.comm.mcp.slack_tools"),)

    def test_refuses_a_server_other_than_the_shared_app(self, foreign_server: FastMCP) -> None:
        with pytest.raises(ForeignServerError, match="'foreign'"):
            import_tool_modules(server=foreign_server, modules=("dev10x.comm.mcp.slack_tools",))


class TestNamespaceRegister:
    @pytest.mark.parametrize("registration", REGISTRATIONS)
    def test_register_returns_its_tool_modules(self, registration: str) -> None:
        module = importlib.import_module(registration)

        registered = module.register(cli_app)

        assert [mod.__name__ for mod in registered] == list(module.TOOL_MODULES)

    @pytest.mark.parametrize("registration", REGISTRATIONS)
    def test_register_refuses_a_foreign_server(
        self,
        registration: str,
        foreign_server: FastMCP,
    ) -> None:
        module = importlib.import_module(registration)

        with pytest.raises(ForeignServerError):
            module.register(foreign_server)


class TestServerCli:
    def test_namespaces_list_the_tool_owning_plugins(self) -> None:
        assert server_cli.CLI_NAMESPACES == ("core", "coding", "comm", "tasks", "teach")

    def test_register_namespaces_collects_every_namespace_module(self) -> None:
        expected: list[ModuleType] = []
        for registration in REGISTRATIONS:
            expected.extend(importlib.import_module(registration).register(cli_app))

        assert server_cli.register_namespaces(server=cli_app) == tuple(expected)

    def test_tool_modules_are_the_registered_modules(self) -> None:
        assert server_cli.TOOL_MODULES == server_cli.register_namespaces(server=cli_app)

    @pytest.mark.parametrize(
        ("name", "owner"),
        [
            ("mktmp", "dev10x.core.mcp.utility_tools"),
            ("pr_get", "dev10x.coding.mcp.github_tools"),
            ("run_tests", "dev10x.coding.mcp.runner_tools"),
            ("slack_thread_is_forward", "dev10x.comm.mcp.slack_tools"),
            ("generate_skill_index", "dev10x.teach.mcp.skill_index_tools"),
        ],
    )
    def test_tool_functions_stay_reachable_as_attributes(self, name: str, owner: str) -> None:
        assert getattr(server_cli, name) is getattr(importlib.import_module(owner), name)

    def test_unknown_attribute_raises(self) -> None:
        with pytest.raises(AttributeError, match="no_such_tool"):
            server_cli.no_such_tool  # noqa: B018
