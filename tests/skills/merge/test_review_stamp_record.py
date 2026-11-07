from __future__ import annotations

import subprocess
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.file_locks import LockTimeoutError
from dev10x.domain.review_stamp import CorruptStampStoreError, ReviewStamp, ReviewStampStore

from dev10x.coding.merge.review_stamp import record_clean_review

_GIT = "dev10x.coding.merge.review_stamp.GitContext"
HEAD = "a" * 40
TREE = "t" * 40


@dataclass
class FakeGit:
    branch: str = "janusz/GH-1830/stamp"
    remote: str = "git@github.com:Dev10x-Guru/Dev10x-Claude.git"
    failure: Exception | None = None

    def run(self, *args: str, timeout: float | None = None) -> str:
        if self.failure is not None:
            raise self.failure
        answers = {
            ("rev-parse", "HEAD"): HEAD,
            ("rev-parse", "HEAD^{tree}"): TREE,
            ("remote", "get-url", "origin"): self.remote,
        }
        return answers[args]


async def _record(*, git: FakeGit) -> SuccessResult[dict] | ErrorResult:
    with patch(_GIT, return_value=git):
        return await record_clean_review()


@pytest.mark.asyncio
async def test_records_the_checked_out_head() -> None:
    result = await _record(git=FakeGit())

    assert isinstance(result, SuccessResult)
    assert result.value["repo"] == "dev10x-guru/dev10x-claude"
    assert result.value["head_sha"] == HEAD
    stored = ReviewStampStore(path=Dev10xConfigDir.review_stamps_json()).read(
        slug="dev10x-guru/dev10x-claude", branch="janusz/GH-1830/stamp"
    )
    assert stored == ReviewStamp(
        head_sha=HEAD, tree_sha=TREE, reviewed_at=result.value["reviewed_at"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(returncode=128, cmd=["git"]),
        subprocess.TimeoutExpired(cmd=["git"], timeout=5),
        OSError("no git"),
    ],
)
async def test_git_failure_is_an_error(failure: Exception) -> None:
    result = await _record(git=FakeGit(failure=failure))

    assert isinstance(result, ErrorResult)
    assert "Cannot read the reviewed head" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["HEAD", "unknown"])
async def test_detached_head_is_an_error(branch: str) -> None:
    result = await _record(git=FakeGit(branch=branch))

    assert isinstance(result, ErrorResult)
    assert "detached" in result.error


@pytest.mark.asyncio
async def test_unparseable_remote_is_an_error() -> None:
    result = await _record(git=FakeGit(remote="not-a-remote"))

    assert isinstance(result, ErrorResult)
    assert "owner/repo" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [CorruptStampStoreError("not a JSON object"), PermissionError("read-only config dir")],
)
async def test_store_write_failure_is_an_error(failure: OSError) -> None:
    with patch.object(ReviewStampStore, "write", side_effect=failure):
        result = await _record(git=FakeGit())

    assert isinstance(result, ErrorResult)
    assert "Cannot write the review stamp store" in result.error


@pytest.mark.asyncio
async def test_locked_store_asks_to_try_again() -> None:
    with patch.object(ReviewStampStore, "write", side_effect=LockTimeoutError("busy")):
        result = await _record(git=FakeGit())

    assert isinstance(result, ErrorResult)
    assert "Please try again" in result.error
