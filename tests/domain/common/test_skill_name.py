from __future__ import annotations

import pytest

from dev10x.domain.common.skill_name import SkillName


class TestParse:
    def test_parses_namespaced(self) -> None:
        name = SkillName.parse("Dev10x:git-commit")

        assert name.namespace == "Dev10x"
        assert name.slug == "git-commit"
        assert str(name) == "Dev10x:git-commit"

    def test_parses_unnamespaced(self) -> None:
        name = SkillName.parse("simple-skill")

        assert name.namespace is None
        assert name.slug == "simple-skill"
        assert str(name) == "simple-skill"

    @pytest.mark.parametrize("raw", ["", ":slug", "ns:", None])
    def test_rejects_invalid(self, raw: object) -> None:
        with pytest.raises((TypeError, ValueError)):
            SkillName.parse(raw)  # type: ignore[arg-type]


class TestProperties:
    def test_short_name_returns_slug(self) -> None:
        assert SkillName.parse("Dev10x:git-commit").short_name == "git-commit"

    def test_safe_path_name_replaces_colon(self) -> None:
        assert SkillName.parse("Dev10x:git-commit").safe_path_name == "Dev10x-git-commit"

    def test_safe_path_name_strips_unsafe_chars(self) -> None:
        # Construct directly to bypass parse validation
        name = SkillName(namespace="Dev10x", slug="bad/skill name!")

        assert name.safe_path_name == "Dev10x-badskillname"


class TestTryParse:
    def test_returns_none_for_invalid(self) -> None:
        assert SkillName.try_parse("") is None

    def test_returns_skill_for_valid(self) -> None:
        name = SkillName.try_parse("foo")

        assert name is not None
        assert name.slug == "foo"
