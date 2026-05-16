import pytest

from dev10x.domain.common.repository_ref import RepositoryRef


class TestParse:
    @pytest.fixture()
    def result(self) -> RepositoryRef:
        return RepositoryRef.parse("owner/repo-name")

    def test_owner(self, result: RepositoryRef) -> None:
        assert result.owner == "owner"

    def test_name(self, result: RepositoryRef) -> None:
        assert result.name == "repo-name"

    def test_str(self, result: RepositoryRef) -> None:
        assert str(result) == "owner/repo-name"


class TestParseInvalid:
    @pytest.mark.parametrize(
        "value",
        [
            "no-slash",
            "too/many/slashes",
            "/missing-owner",
            "missing-name/",
            "",
        ],
    )
    def test_raises_value_error(self, value: str) -> None:
        with pytest.raises(ValueError, match="Invalid repository reference"):
            RepositoryRef.parse(value)


class TestFrozen:
    def test_immutable(self) -> None:
        ref = RepositoryRef(owner="a", name="b")
        with pytest.raises(AttributeError):
            ref.owner = "c"  # type: ignore[misc]
