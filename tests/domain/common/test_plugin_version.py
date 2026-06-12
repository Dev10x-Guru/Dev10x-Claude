from __future__ import annotations

import pytest

from dev10x.domain.common.plugin_version import SEMVER_PATTERN, PluginVersion


class TestParse:
    @pytest.mark.parametrize(
        "raw,major,minor,patch",
        [
            ("0.79.0", 0, 79, 0),
            ("1.2.3", 1, 2, 3),
            ("10.0.255", 10, 0, 255),
        ],
    )
    def test_parses_canonical_form(self, raw: str, major: int, minor: int, patch: int) -> None:
        version = PluginVersion.parse(raw)

        assert version.major == major
        assert version.minor == minor
        assert version.patch == patch
        assert str(version) == raw

    @pytest.mark.parametrize(
        "raw",
        ["", "1.2", "1.2.3.4", "v1.2.3", "1.2.x", "0.46.0.dev0", "1.2.3 "],
    )
    def test_rejects_invalid_forms(self, raw: str) -> None:
        with pytest.raises(ValueError):
            PluginVersion.parse(raw)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValueError):
            PluginVersion.parse(None)  # type: ignore[arg-type]


class TestTryParse:
    def test_returns_version_on_success(self) -> None:
        version = PluginVersion.try_parse("3.4.5")

        assert version == PluginVersion(major=3, minor=4, patch=5)

    def test_returns_none_on_failure(self) -> None:
        assert PluginVersion.try_parse("not-a-version") is None


class TestOrdering:
    def test_orders_by_major_minor_patch(self) -> None:
        assert PluginVersion.parse("0.79.0") < PluginVersion.parse("0.80.0")
        assert PluginVersion.parse("1.0.0") > PluginVersion.parse("0.99.99")
        assert PluginVersion.parse("1.2.3") <= PluginVersion.parse("1.2.3")
        assert PluginVersion.parse("1.2.4") >= PluginVersion.parse("1.2.3")

    def test_equal_versions_compare_equal(self) -> None:
        assert PluginVersion.parse("2.2.2") == PluginVersion.parse("2.2.2")

    def test_sorts_a_list(self) -> None:
        versions = [PluginVersion.parse(v) for v in ["1.0.0", "0.9.0", "1.0.1"]]

        assert sorted(versions) == [
            PluginVersion.parse("0.9.0"),
            PluginVersion.parse("1.0.0"),
            PluginVersion.parse("1.0.1"),
        ]


class TestSortKey:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0.79.0", (0, 79, 0)),
            ("1.2", (1, 2)),
            ("1.2.3.4", (1, 2, 3, 4)),
            ("garbage", (0,)),
            ("0.46.0.dev0", (0,)),
        ],
    )
    def test_lenient_tuple_for_directory_names(self, raw: str, expected: tuple[int, ...]) -> None:
        assert PluginVersion.sort_key(raw) == expected

    def test_orders_directory_names(self) -> None:
        names = ["0.9.0", "0.79.0", "0.100.0", "0.8.0"]

        assert sorted(names, key=PluginVersion.sort_key)[-1] == "0.100.0"


class TestAsTuple:
    def test_returns_major_minor_patch_tuple(self) -> None:
        assert PluginVersion.parse("4.5.6").as_tuple() == (4, 5, 6)


def test_pattern_exposed_as_string() -> None:
    assert SEMVER_PATTERN == r"\d+\.\d+\.\d+"
