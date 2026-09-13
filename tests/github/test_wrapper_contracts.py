"""Contract gaps in the MCP GitHub wrappers.

Five defects that all surfaced as "the wrapper accepted the call and
returned something plausible", so none of them failed loudly at the
boundary:

* GH-1269 — ``create_pr`` is the only PR wrapper without ``repo``.
* GH-1265 — ``pr_get`` exposes no changed-file list, so callers
  hand-roll ``gh api`` and inherit its 30-item page.
* GH-1267 — ``merge_pr`` merges the head at call time, not the head
  the gate verified.
* GH-1256 — ``create_pr`` emits no ``Fixes:`` trailer when the caller
  passes ``issue_id`` alone.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import SuccessResult, ok

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")

_JOB_STORY = (
    "**When** a PR is opened, **the maintainer wants to** ship it, **so the crew can** move on."
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PR_GET_SCRIPT = _REPO_ROOT / "skills/gh-context/scripts/gh-pr-get.sh"


@pytest.fixture
def mock_resolve_repo():
    with patch.object(
        gh,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestCreatePrAcceptsRepo:
    """GH-1269: the MCP signature omits the sibling wrappers' ``repo``."""

    def test_mcp_create_pr_declares_repo_parameter(self) -> None:
        from dev10x.mcp import github_tools

        parameters = inspect.signature(github_tools.create_pr).parameters
        assert "repo" in parameters

    @pytest.mark.parametrize("tool_name", ["pr_get", "update_pr", "merge_pr", "create_pr"])
    def test_pr_wrappers_accept_repo_uniformly(self, tool_name: str) -> None:
        from dev10x.mcp import github_tools

        parameters = inspect.signature(getattr(github_tools, tool_name)).parameters
        assert "repo" in parameters, f"{tool_name} breaks the repo= convention"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_repo_reaches_the_create_pr_script(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(
            stdout="https://github.com/owner/repo/pull/7\n7\n"
        )

        with patch("dev10x.domain.git_context.GitContext") as mock_ctx:
            mock_ctx.return_value.branch = "feature/x"
            result = await gh.create_pr(
                title="t",
                issue_id="1269",
                job_story=_JOB_STORY,
                repo="owner/repo",
            )

        assert isinstance(result, SuccessResult)
        assert "owner/repo" in mock_run_script.call_args.args


class TestPrGetExposesChangedFiles:
    """GH-1265: no ``files`` field, so callers hand-roll a paged ``gh api``."""

    def test_files_is_in_the_comma_separated_field_set(self) -> None:
        fields_line = next(
            line for line in _PR_GET_SCRIPT.read_text().splitlines() if line.startswith("FIELDS=")
        )
        field_names = fields_line.removeprefix("FIELDS=").split(",")
        assert "files" in field_names


class TestMergePrPinsTheVerifiedHead:
    """GH-1267: a push between gate and merge ships unreviewed code."""

    def test_domain_merge_pr_declares_expected_head_sha(self) -> None:
        parameters = inspect.signature(gh.merge_pr).parameters
        assert "expected_head_sha" in parameters

    def test_mcp_merge_pr_declares_expected_head_sha(self) -> None:
        from dev10x.mcp import github_tools

        parameters = inspect.signature(github_tools.merge_pr).parameters
        assert "expected_head_sha" in parameters

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_expected_head_sha_becomes_match_head_commit(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42, expected_head_sha="deadbeef")

        assert isinstance(result, SuccessResult)
        called_args = mock_run.call_args.kwargs["args"]
        assert "--match-head-commit" in called_args
        assert called_args[called_args.index("--match-head-commit") + 1] == "deadbeef"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_flag_absent_when_no_sha_pinned(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        mock_run.return_value = _completed(stdout="merged\n")

        await gh.merge_pr(pr_number=42)

        assert "--match-head-commit" not in mock_run.call_args.kwargs["args"]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_payload_echoes_the_pinned_sha(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42, expected_head_sha="deadbeef")

        assert isinstance(result, SuccessResult)
        assert result.value["expected_head_sha"] == "deadbeef"


class TestCreatePrAlwaysEmitsFixes:
    """GH-1256: ``issue_id`` alone produced a body with no trailer.

    ``create-pr.sh`` derives the trailer from argument 4 (``fixes_url``)
    only, so a caller passing ``issue_id`` — the documented way to link
    the issue — got a body the hygiene bot rejects. The fix belongs in
    the domain layer: it already knows the issue id, and the script
    already splits a multi-ref ``fixes_url`` on commas.
    """

    @staticmethod
    def _fixes_arg(mock_run_script: AsyncMock) -> str:
        # create-pr.sh positional 4 — args are (title, job_story,
        # issue_id, fixes_url, ...) after the script path.
        return mock_run_script.call_args.args[4]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_issue_id_alone_still_yields_a_fixes_ref(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(
            stdout="https://github.com/owner/repo/pull/7\n7\n"
        )

        with patch("dev10x.domain.git_context.GitContext") as mock_ctx:
            mock_ctx.return_value.branch = "feature/x"
            await gh.create_pr(title="t", issue_id="1245", job_story=_JOB_STORY)

        assert "1245" in self._fixes_arg(mock_run_script)

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_closes_members_become_fixes_refs(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        """`Closes` never fires on a develop merge (GH-958)."""
        mock_run_script.return_value = _completed(
            stdout="https://github.com/owner/repo/pull/7\n7\n"
        )

        with patch("dev10x.domain.git_context.GitContext") as mock_ctx:
            mock_ctx.return_value.branch = "feature/x"
            await gh.create_pr(
                title="t",
                issue_id="1245",
                job_story=_JOB_STORY,
                closes=[1251, 1226],
            )

        fixes_arg = self._fixes_arg(mock_run_script)
        assert "1251" in fixes_arg
        assert "1226" in fixes_arg

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run_script", new_callable=AsyncMock)
    async def test_explicit_fixes_url_still_wins(
        self,
        mock_run_script: AsyncMock,
    ) -> None:
        mock_run_script.return_value = _completed(
            stdout="https://github.com/owner/repo/pull/7\n7\n"
        )
        url = "https://github.com/owner/repo/issues/99"

        with patch("dev10x.domain.git_context.GitContext") as mock_ctx:
            mock_ctx.return_value.branch = "feature/x"
            await gh.create_pr(
                title="t",
                issue_id="1245",
                job_story=_JOB_STORY,
                fixes_url=url,
            )

        assert url in self._fixes_arg(mock_run_script)
