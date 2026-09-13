"""A relative `cwd` has no correct meaning at the MCP seam (GH-1264).

The server is long-lived and resolves a relative path against the
directory it was spawned in, not the caller's checkout.
``run_node_tests(cwd="apps/web")`` therefore ran somewhere else, passed,
and reported green for a tree the caller had never written to — not
friction but manufactured evidence, a passing gate certifying the wrong
artefact.

The refusal lives in ``use_cwd`` rather than in the one tool that
surfaced it: every MCP tool takes ``cwd=`` through the same seam, so a
fix scoped to ``run_node_tests`` would leave the identical trap set for
the other fifty.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ok
from dev10x.mcp import server_cli as cli_server
from dev10x.subprocess_utils import RelativeCwdError, effective_cwd, use_cwd


class TestUseCwdRejectsARelativePath:
    @pytest.mark.parametrize(
        "relative",
        ["apps/web", "./apps/web", "../sibling", "web", ""],
    )
    def test_a_relative_path_raises(self, relative: str) -> None:
        with pytest.raises(ValueError):
            with use_cwd(relative):
                pass  # pragma: no cover - the bind must not happen

    def test_the_refusal_is_distinguishable_from_a_server_fault(self) -> None:
        # Both reach the caller as an exception; only the type says
        # "fix your argument" rather than "the server broke".
        with pytest.raises(RelativeCwdError):
            with use_cwd("apps/web"):
                pass  # pragma: no cover - the bind must not happen

    def test_the_error_names_the_offending_value(self) -> None:
        # The caller has to be able to see WHICH argument was wrong; a
        # bare "must be absolute" sends them reading the whole call.
        with pytest.raises(ValueError, match="apps/web"):
            with use_cwd("apps/web"):
                pass  # pragma: no cover - the bind must not happen

    def test_the_error_says_what_to_pass_instead(self) -> None:
        with pytest.raises(ValueError, match="absolute"):
            with use_cwd("apps/web"):
                pass  # pragma: no cover - the bind must not happen

    def test_nothing_is_bound_when_the_path_is_refused(self) -> None:
        # A refusal that still bound the value would leave every later
        # subprocess in the block pointed at the wrong tree.
        with pytest.raises(ValueError):
            with use_cwd("apps/web"):
                pass  # pragma: no cover - the bind must not happen

        assert effective_cwd() is None


class TestUseCwdStillAcceptsWhatItAlwaysDid:
    def test_an_absolute_path_binds(self, tmp_path) -> None:
        with use_cwd(str(tmp_path)):
            assert effective_cwd() == str(tmp_path)

    def test_none_leaves_the_binding_untouched(self) -> None:
        with use_cwd(None):
            assert effective_cwd() is None

    def test_the_binding_is_released_on_exit(self, tmp_path) -> None:
        with use_cwd(str(tmp_path)):
            pass

        assert effective_cwd() is None

    def test_a_nested_bind_restores_the_outer_one(self, tmp_path) -> None:
        outer = tmp_path / "outer"
        inner = tmp_path / "inner"
        with use_cwd(str(outer)):
            with use_cwd(str(inner)):
                assert effective_cwd() == str(inner)
            assert effective_cwd() == str(outer)


def _node_ok() -> object:
    return ok(
        {
            "returncode": 0,
            "runner": "jest",
            "script": "test",
            "summary": "7 passed",
            "passed": 7,
            "failed": 0,
            "skipped": 0,
            "todo": 0,
            "total": 7,
            "stdout": "",
            "stderr": "",
        }
    )


class TestRunNodeTestsReportsWhereItRan:
    """A green payload must say which tree produced it (GH-1264)."""

    @pytest.mark.asyncio
    @patch("dev10x.runner.run_node_tests", new_callable=AsyncMock)
    async def test_the_payload_echoes_the_bound_cwd(self, mock_fn: AsyncMock, tmp_path) -> None:
        mock_fn.return_value = _node_ok()

        result = await cli_server.run_node_tests(cwd=str(tmp_path))

        assert result["cwd"] == str(tmp_path)

    @pytest.mark.asyncio
    @patch("dev10x.runner.run_node_tests", new_callable=AsyncMock)
    async def test_an_unbound_run_reports_the_process_directory(self, mock_fn: AsyncMock) -> None:
        mock_fn.return_value = _node_ok()

        result = await cli_server.run_node_tests()

        assert result["cwd"] == os.getcwd()

    @pytest.mark.asyncio
    @patch("dev10x.runner.run_node_tests", new_callable=AsyncMock)
    async def test_a_relative_cwd_never_reaches_the_runner(self, mock_fn: AsyncMock) -> None:
        # The defect was a run that HAPPENED against the wrong tree, so
        # refusing after launching it would fix nothing.
        mock_fn.return_value = _node_ok()

        with pytest.raises(ValueError):
            await cli_server.run_node_tests(cwd="apps/web")

        mock_fn.assert_not_called()
