"""GH-1272: merge_pr can execute under the GitHub App identity.

Without it `merged_by` names the same engineer for the orchestrator,
every crew worker and the human, so a merge that bypassed the pre-merge
gate cannot be attributed even in principle.

The transport is opt-in and never fails the merge: when it cannot run it
falls back to the engineer identity and reports why in ``bot_fallback``,
because a repo whose ruleset restricts who may merge depends on that.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import SuccessResult, ok

gh = pytest.importorskip("dev10x.github", reason="dev10x not installed")


@pytest.fixture
def mock_resolve_repo():
    with patch.object(
        gh,
        "_resolve_repo",
        new_callable=AsyncMock,
        return_value=ok(RepositoryRef(owner="owner", name="repo")),
    ) as mock:
        yield mock


@pytest.fixture
def bot_env():
    """A resolvable installation token."""
    with patch.object(
        gh, "_bot_env", new_callable=AsyncMock, return_value={"GH_TOKEN": "ghs_x"}
    ) as mock:
        yield mock


@pytest.fixture
def no_bot_env():
    with patch.object(gh, "_bot_env", new_callable=AsyncMock, return_value=None) as mock:
        yield mock


def _completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestBotTransportSelected:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_merges_through_the_rest_endpoint(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        mock_api.return_value = _completed(stdout='{"merged": true}')

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=False)

        assert isinstance(result, SuccessResult)
        endpoint = mock_api.call_args.args[0]
        assert endpoint == "repos/owner/repo/pulls/42/merge"
        assert mock_api.call_args.kwargs["method"] == "PUT"
        assert mock_api.call_args.kwargs["as_bot"] is True

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_payload_reports_the_bot_identity(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        mock_api.return_value = _completed(stdout='{"merged": true}')

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=False)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "bot"
        assert result.value["bot_fallback"] is None

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_strategy_becomes_merge_method(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        mock_api.return_value = _completed(stdout='{"merged": true}')

        await gh.merge_pr(pr_number=42, strategy="squash", use_bot=True, delete_branch=False)

        assert mock_api.call_args.kwargs["fields"]["merge_method"] == "squash"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_expected_head_sha_becomes_the_sha_field(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        """The REST endpoint's own 409-on-mismatch guard (GH-1267)."""
        mock_api.return_value = _completed(stdout='{"merged": true}')

        await gh.merge_pr(
            pr_number=42, use_bot=True, delete_branch=False, expected_head_sha="deadbeef"
        )

        assert mock_api.call_args.kwargs["fields"]["sha"] == "deadbeef"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_merge_failure_surfaces_as_error(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        mock_api.return_value = _completed(returncode=1, stderr="Head branch was modified")

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=False)

        assert not isinstance(result, SuccessResult)
        assert "Head branch was modified" in result.error


class TestFallsBackLoudly:
    """Never fail the merge — degrade to the engineer identity and say so."""

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_no_installation_token_falls_back(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
        no_bot_env,
    ) -> None:
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42, use_bot=True)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
        assert result.value["bot_fallback"] == "no installation token"
        assert mock_run.call_args.kwargs["args"][:3] == ["gh", "pr", "merge"]

    @pytest.mark.parametrize("flag", ["admin", "auto"])
    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_admin_and_auto_keep_the_cli_path(
        self,
        mock_run: AsyncMock,
        flag: str,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        """Neither has a REST equivalent; honouring them beats the identity."""
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42, use_bot=True, **{flag: True})

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
        assert "admin/auto" in result.value["bot_fallback"]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_default_is_unchanged_behaviour(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
    ) -> None:
        """Opt-in: an unconfigured caller merges exactly as before."""
        mock_run.return_value = _completed(stdout="merged\n")

        with patch.object(gh.AppConfig, "load", return_value=None):
            result = await gh.merge_pr(pr_number=42)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
        assert result.value["bot_fallback"] == "not requested"


class TestDurablePreference:
    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_merge_bot_preference_enables_the_transport(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        from dev10x.github.app_auth import AppConfig

        mock_api.return_value = _completed(stdout='{"merged": true}')
        config = AppConfig(app_id="1", private_key_path=gh.Path("/k"), merge_bot=True)

        with patch.object(gh.AppConfig, "load", return_value=config):
            result = await gh.merge_pr(pr_number=42, delete_branch=False)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "bot"

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    async def test_explicit_false_overrides_the_preference(
        self,
        mock_run: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        from dev10x.github.app_auth import AppConfig

        mock_run.return_value = _completed(stdout="merged\n")
        config = AppConfig(app_id="1", private_key_path=gh.Path("/k"), merge_bot=True)

        with patch.object(gh.AppConfig, "load", return_value=config):
            result = await gh.merge_pr(pr_number=42, use_bot=False)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
