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
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import SuccessResult, err, ok

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
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_a_refused_bot_merge_degrades_to_the_cli(
        self,
        mock_api: AsyncMock,
        mock_run: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        """A ruleset excluding the bot must not block the merge (GH-1272)."""
        mock_api.return_value = _completed(returncode=1, stderr="Resource not accessible")
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=False)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
        assert "Resource not accessible" in result.value["bot_fallback"]
        assert mock_run.call_args.kwargs["args"][:3] == ["gh", "pr", "merge"]

    @pytest.mark.asyncio
    @patch("dev10x.github.async_run", new_callable=AsyncMock)
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_merged_false_in_the_body_is_not_success(
        self,
        mock_api: AsyncMock,
        mock_run: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        """A 200 whose body says merged: false is still a failed merge."""
        mock_api.return_value = _completed(
            stdout='{"merged": false, "message": "Head branch was modified"}'
        )
        mock_run.return_value = _completed(stdout="merged\n")

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=False)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
        assert "Head branch was modified" in result.value["bot_fallback"]

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_the_token_is_minted_once_and_threaded_through(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        """Re-resolving could fail into engineer creds while claiming 'bot'."""
        mock_api.return_value = _completed(stdout='{"merged": true}')

        await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=False)

        assert bot_env.await_count == 1
        assert mock_api.call_args.kwargs["bot_env"] == {"GH_TOKEN": "ghs_x"}


class TestBranchDeletion:
    """The REST merge does not delete the ref — a second call must."""

    @pytest.fixture
    def head_ref(self):
        with patch.object(
            gh,
            "pr_get",
            new_callable=AsyncMock,
            return_value=ok({"headRefName": "feature/x"}),
        ) as mock:
            yield mock

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_deletes_the_head_ref(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
        head_ref,
    ) -> None:
        mock_api.return_value = _completed(stdout='{"merged": true}')

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=True)

        assert isinstance(result, SuccessResult)
        assert result.value["branch_deleted"] is True
        assert result.value["branch_deletion_error"] is None
        deletion = mock_api.call_args_list[-1]
        assert deletion.args[0] == "repos/owner/repo/git/refs/heads/feature/x"
        assert deletion.kwargs["method"] == "DELETE"

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_refused_deletion_still_reports_the_merge(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
        head_ref,
    ) -> None:
        """A protected head ref must not turn a completed merge into an error."""
        mock_api.side_effect = [
            _completed(stdout='{"merged": true}'),
            _completed(returncode=1, stderr="Reference cannot be deleted"),
        ]

        result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=True)

        assert isinstance(result, SuccessResult)
        assert result.value["branch_deleted"] is False
        assert "cannot be deleted" in result.value["branch_deletion_error"]

    @pytest.mark.asyncio
    @patch("dev10x.github._gh_api_raw", new_callable=AsyncMock)
    async def test_unresolvable_head_ref_skips_the_delete(
        self,
        mock_api: AsyncMock,
        mock_resolve_repo,
        bot_env,
    ) -> None:
        mock_api.return_value = _completed(stdout='{"merged": true}')

        with patch.object(gh, "pr_get", new_callable=AsyncMock, return_value=err("no such PR")):
            result = await gh.merge_pr(pr_number=42, use_bot=True, delete_branch=True)

        assert isinstance(result, SuccessResult)
        assert mock_api.call_count == 1
        assert "could not resolve head branch" in result.value["branch_deletion_error"]


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
        config = AppConfig(app_id="1", private_key_path=Path("/k"), merge_bot=True)

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
        config = AppConfig(app_id="1", private_key_path=Path("/k"), merge_bot=True)

        with patch.object(gh.AppConfig, "load", return_value=config):
            result = await gh.merge_pr(pr_number=42, use_bot=False)

        assert isinstance(result, SuccessResult)
        assert result.value["merged_as"] == "engineer"
