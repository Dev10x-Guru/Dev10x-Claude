"""Tests for org/repo resolution behind repo-addressed configs (GH-1375)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.session.repo_address import (
    NO_ORIGIN_REASON,
    parse_name_with_owner,
    resolve_name_with_owner,
)


class TestParseNameWithOwner:
    @pytest.mark.parametrize(
        "url",
        [
            "git@github.com:Dev10x-Guru/Dev10x-Claude.git",
            "https://github.com/Dev10x-Guru/Dev10x-Claude.git",
            "https://github.com/Dev10x-Guru/Dev10x-Claude",
            "ssh://git@github.com/Dev10x-Guru/Dev10x-Claude.git",
            "  git@github.com:Dev10x-Guru/Dev10x-Claude.git\n",
        ],
    )
    def test_every_clone_style_yields_the_same_pair(self, url: str) -> None:
        """Protocol independence is the point of matching org/repo (ADR-0026)."""
        assert parse_name_with_owner(url) == "Dev10x-Guru/Dev10x-Claude"

    def test_nested_group_takes_the_last_two_segments(self) -> None:
        assert parse_name_with_owner("https://gitlab.com/grp/sub/repo.git") == "sub/repo"

    @pytest.mark.parametrize("url", ["", "   ", "repo.git", "https://github.com/solo"])
    def test_unrecognisable_urls_yield_none(self, url: str) -> None:
        assert parse_name_with_owner(url) is None


class TestResolveNameWithOwner:
    def test_success_carries_the_pair(self) -> None:
        with patch(
            "dev10x.domain.git_context.GitContext.run",
            return_value="git@github.com:org/repo.git",
        ):
            result = resolve_name_with_owner()
        assert isinstance(result, SuccessResult)
        assert result.value == "org/repo"

    @pytest.mark.parametrize(
        "raised",
        [
            subprocess.CalledProcessError(1, "git"),
            subprocess.TimeoutExpired("git", 5.0),
            OSError("git missing"),
        ],
    )
    def test_a_missing_origin_names_the_cause(self, raised: Exception) -> None:
        with patch("dev10x.domain.git_context.GitContext.run", side_effect=raised):
            result = resolve_name_with_owner()
        assert isinstance(result, ErrorResult)
        assert result.error == NO_ORIGIN_REASON

    def test_an_unparseable_remote_names_the_url(self) -> None:
        with patch("dev10x.domain.git_context.GitContext.run", return_value="weird-remote"):
            result = resolve_name_with_owner()
        assert isinstance(result, ErrorResult)
        assert "weird-remote" in result.error
