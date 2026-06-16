from __future__ import annotations

import pytest

from dev10x.domain.common.branch_name import BranchName


class TestParseConvention:
    def test_parses_regular_branch(self) -> None:
        branch = BranchName.parse("janusz/GH-241/value-objects")

        assert branch.username == "janusz"
        assert branch.ticket is not None
        assert str(branch.ticket) == "GH-241"
        assert branch.worktree is None
        assert branch.slug == "value-objects"
        assert branch.follows_convention is True

    def test_parses_worktree_branch(self) -> None:
        branch = BranchName.parse("janusz/PAY-1/app-pos-7/fix-timeout")

        assert branch.username == "janusz"
        assert str(branch.ticket) == "PAY-1"
        assert branch.worktree == "app-pos-7"
        assert branch.slug == "fix-timeout"
        assert branch.follows_convention is True

    @pytest.mark.parametrize(
        "raw",
        [
            "develop",
            "main",
            "feature-branch",
            "username/notaticket/slug",
            "janusz/GH-1/Bad-Slug",
            "janusz/GH-1/wt/bad slug",
            "too/many/slashes/here/wow",
        ],
    )
    def test_non_conforming_branches_do_not_follow_convention(self, raw: str) -> None:
        branch = BranchName.parse(raw)

        assert branch.follows_convention is False


class TestProtected:
    @pytest.mark.parametrize("name", ["main", "master", "develop", "trunk"])
    def test_protected_branches(self, name: str) -> None:
        assert BranchName.parse(name).is_protected is True

    def test_feature_branch_not_protected(self) -> None:
        assert BranchName.parse("janusz/GH-1/work").is_protected is False


class TestParseRejection:
    def test_parse_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            BranchName.parse("")

    def test_try_parse_returns_none_for_empty(self) -> None:
        assert BranchName.try_parse("") is None
