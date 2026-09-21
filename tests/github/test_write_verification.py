"""GH-1424: a write wrapper must report what GitHub did, not its own input.

`.claude/rules/mcp-tools.md` § "A write is a request, not a receipt"
(GH-1099) says the transport can drop a state-changing call with no error
payload, and instructs callers to re-read the field they set. Only
`create_pr` implemented it; the rest built their success payload from the
arguments they were handed.

The sharpest case was `pr_ready` returning `{"draft": undo}` — the input
echoed back, so the field could never disagree with the request and
carried no information, while looking exactly like confirmation.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import dev10x.github as gh
from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok


def _completed(*, returncode: int = 0, stdout: str = "{}", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def resolved_repo(monkeypatch: pytest.MonkeyPatch):
    from dev10x.domain.common.repository_ref import RepositoryRef

    async def fake_resolve(_repo):
        return ok(RepositoryRef.parse("owner/repo"))

    monkeypatch.setattr(gh, "_resolve_repo", fake_resolve)


class TestPrReadyVerifiesDraftState:
    @pytest.mark.asyncio
    async def test_draft_reflects_github_not_the_argument(self, resolved_repo) -> None:
        with (
            patch("dev10x.github.async_run", new_callable=AsyncMock) as mock_run,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_run.return_value = _completed()
            mock_get.return_value = ok({"isDraft": False})
            result = await gh.pr_ready(pr_number=42, repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["draft"] is False
        assert result.value["draft_verified"] is True

    @pytest.mark.asyncio
    async def test_undo_is_verified_too(self, resolved_repo) -> None:
        with (
            patch("dev10x.github.async_run", new_callable=AsyncMock) as mock_run,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_run.return_value = _completed()
            mock_get.return_value = ok({"isDraft": True})
            result = await gh.pr_ready(pr_number=42, repo="owner/repo", undo=True)

        assert isinstance(result, SuccessResult)
        assert result.value["draft"] is True
        assert result.value["draft_verified"] is True

    @pytest.mark.asyncio
    async def test_a_dropped_flip_is_reported_as_an_error(self, resolved_repo) -> None:
        """`gh` exited 0 but the PR is still a draft — the write vanished.

        This is the case the old payload could not express: it would have
        returned `{"draft": False}` and the caller would have gone on to
        merge, failing with 'Pull Request is still a draft'.
        """
        with (
            patch("dev10x.github.async_run", new_callable=AsyncMock) as mock_run,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_run.return_value = _completed()
            mock_get.return_value = ok({"isDraft": True})
            result = await gh.pr_ready(pr_number=42, repo="owner/repo")

        assert isinstance(result, ErrorResult)
        assert "still a draft" in result.error
        assert "42" in result.error

    @pytest.mark.asyncio
    async def test_an_unreadable_verification_warns_rather_than_fails(self, resolved_repo) -> None:
        """Not being able to check is not evidence the flip failed."""
        with (
            patch("dev10x.github.async_run", new_callable=AsyncMock) as mock_run,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_run.return_value = _completed()
            mock_get.return_value = err("gh unreachable")
            result = await gh.pr_ready(pr_number=42, repo="owner/repo")

        assert isinstance(result, SuccessResult)
        assert result.value["draft_verified"] is False
        assert "could not be read back" in result.value["warning"]

    @pytest.mark.asyncio
    async def test_a_failed_flip_never_reaches_verification(self, resolved_repo) -> None:
        with (
            patch("dev10x.github.async_run", new_callable=AsyncMock) as mock_run,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_run.return_value = _completed(returncode=1, stderr="no such PR")
            result = await gh.pr_ready(pr_number=42, repo="owner/repo")

        assert isinstance(result, ErrorResult)
        mock_get.assert_not_awaited()


class TestUpdatePrVerifiesTheWrite:
    @pytest.mark.asyncio
    async def test_a_landed_body_is_verified(self, resolved_repo) -> None:
        with (
            patch("dev10x.github._gh_api_raw", new_callable=AsyncMock) as mock_api,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_api.return_value = _completed()
            mock_get.return_value = ok({"body": "the new body"})
            result = await gh.update_pr(pr_number=42, body="the new body")

        assert isinstance(result, SuccessResult)
        assert result.value["write_verified"] is True

    @pytest.mark.asyncio
    async def test_a_dropped_body_write_is_reported(self, resolved_repo) -> None:
        with (
            patch("dev10x.github._gh_api_raw", new_callable=AsyncMock) as mock_api,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_api.return_value = _completed()
            mock_get.return_value = ok({"body": "the OLD body"})
            result = await gh.update_pr(pr_number=42, body="the new body")

        assert isinstance(result, ErrorResult)
        assert "body" in result.error
        assert "did not land" in result.error

    @pytest.mark.asyncio
    async def test_a_dropped_title_write_is_reported(self, resolved_repo) -> None:
        with (
            patch("dev10x.github._gh_api_raw", new_callable=AsyncMock) as mock_api,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_api.return_value = _completed()
            mock_get.return_value = ok({"title": "Old title"})
            result = await gh.update_pr(pr_number=42, title="New title")

        assert isinstance(result, ErrorResult)
        assert "title" in result.error

    @pytest.mark.parametrize(
        "sent, observed",
        [
            ("line one\nline two", "line one\r\nline two"),
            ("body text\n", "body text"),
            ("  body text  ", "body text"),
        ],
    )
    @pytest.mark.asyncio
    async def test_githubs_own_reformatting_is_not_a_dropped_write(
        self,
        resolved_repo,
        sent: str,
        observed: str,
    ) -> None:
        """GitHub stores CRLF and trims — a byte comparison cries wolf."""
        with (
            patch("dev10x.github._gh_api_raw", new_callable=AsyncMock) as mock_api,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_api.return_value = _completed()
            mock_get.return_value = ok({"body": observed})
            result = await gh.update_pr(pr_number=42, body=sent)

        assert isinstance(result, SuccessResult)

    @pytest.mark.asyncio
    async def test_an_unreadable_verification_warns_rather_than_fails(self, resolved_repo) -> None:
        with (
            patch("dev10x.github._gh_api_raw", new_callable=AsyncMock) as mock_api,
            patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get,
        ):
            mock_api.return_value = _completed()
            mock_get.return_value = err("gh unreachable")
            result = await gh.update_pr(pr_number=42, body="x")

        assert isinstance(result, SuccessResult)
        assert result.value["write_verified"] is False

    @pytest.mark.asyncio
    async def test_a_milestone_only_update_skips_the_pr_read(
        self, resolved_repo, monkeypatch
    ) -> None:
        """Nothing was PATCHed on the PR, so there is nothing to re-read.

        `_set_pr_milestone` owns that write and its own confirmation.
        """

        async def fake_set(**_kwargs):
            return ok({"number": 56})

        monkeypatch.setattr(gh, "_set_pr_milestone", fake_set)

        with patch("dev10x.github.pr_get", new_callable=AsyncMock) as mock_get:
            result = await gh.update_pr(pr_number=42, milestone="56")

        assert isinstance(result, SuccessResult)
        mock_get.assert_not_awaited()


class TestSelfVerificationIsStructural:
    """The rule was prose, and prose is how it stayed unimplemented.

    An AST check, so a future wrapper cannot quietly go back to building
    its success payload from its own arguments.
    """

    VERIFYING_WRAPPERS = ("create_pr", "update_pr", "pr_ready")

    @pytest.fixture(scope="class")
    def module_ast(self) -> ast.Module:
        source = Path(gh.__file__).read_text()
        return ast.parse(source)

    @staticmethod
    def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
                return node
        raise AssertionError(f"{name} not found in dev10x.github")

    @pytest.mark.parametrize("wrapper", VERIFYING_WRAPPERS)
    def test_the_wrapper_reads_the_pr_back(self, module_ast, wrapper: str) -> None:
        func = self._function(module_ast, wrapper)

        reads = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "pr_get"
        ]

        assert reads, (
            f"{wrapper} documents self-verification but never calls pr_get. "
            "A write is a request, not a receipt (GH-1099/GH-1424)."
        )

    def test_pr_ready_does_not_echo_its_own_argument(self, module_ast) -> None:
        """The specific regression: `{"draft": undo}`."""
        func = self._function(module_ast, "pr_ready")

        echoes = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Dict)
            and any(
                isinstance(key, ast.Constant) and key.value == "draft"
                for key in node.keys
                if key is not None
            )
            and any(isinstance(value, ast.Name) and value.id == "undo" for value in node.values)
        ]

        assert not echoes, (
            "pr_ready returns its own `undo` argument as `draft` — the field "
            "can never disagree with the request, so it confirms nothing."
        )
