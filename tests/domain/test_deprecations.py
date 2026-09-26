import re
import tomllib
from pathlib import Path

import pytest

from dev10x.domain.deprecations import (
    REGISTER,
    WINDOW_MINOR_VERSIONS,
    Audience,
    Deprecation,
    UnparsableVersionError,
    due,
    parse_release,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER_LANDED_MINOR = 106

SHIM_MARKER = re.compile(
    r"deprecated\s+(?:alias|legacy)|\.\.\s+deprecated::|for\W+one\s+release",
    re.IGNORECASE,
)


def _current_version() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["version"]


def _files_carrying_a_shim_marker() -> list[str]:
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src").rglob("*.py")
        if SHIM_MARKER.search(path.read_text())
    )


def _registered_locations() -> set[str]:
    return {location for entry in REGISTER for location in entry.locations}


def _entry_id(entry: Deprecation) -> str:
    return f"{entry.audience}:{entry.name}"


class TestParseRelease:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("0.106.0", (0, 106, 0)),
            ("0.107.0.dev0", (0, 107, 0)),
            ("1.2.3rc1", (1, 2, 3)),
        ],
    )
    def test_reads_release_ignoring_suffix(
        self,
        version: str,
        expected: tuple[int, int, int],
    ) -> None:
        assert parse_release(version) == expected

    def test_rejects_non_release(self) -> None:
        with pytest.raises(UnparsableVersionError, match="Not a release version"):
            parse_release("dev")


class TestIsDue:
    @pytest.fixture
    def entry(self) -> Deprecation:
        return Deprecation(
            name="old_name",
            audience=Audience.PYTHON,
            since="0.100.0",
            removed_in="0.107.0",
            replacement="new_name",
            issue="GH-0",
            locations=(),
        )

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("0.106.0", False),
            ("0.106.9", False),
            ("0.107.0.dev0", True),
            ("0.107.0", True),
            ("0.108.0.dev0", True),
        ],
    )
    def test_turns_due_on_the_dev0_bump(
        self,
        entry: Deprecation,
        version: str,
        expected: bool,
    ) -> None:
        assert entry.is_due(version=version) is expected


class TestDue:
    def test_lists_nothing_before_any_removal(self) -> None:
        assert due(version="0.0.1") == []

    def test_lists_everything_far_past_every_removal(self) -> None:
        assert due(version="99.0.0") == list(REGISTER)


class TestRegisterIsEnforced:
    @pytest.mark.parametrize("entry", REGISTER, ids=_entry_id)
    def test_shim_is_not_past_its_removal_version(self, entry: Deprecation) -> None:
        assert not entry.is_due(version=_current_version()), (
            f"{entry.name} ({entry.audience}, {entry.issue}) reached its removal "
            f"version {entry.removed_in}. Remove the shim and its register entry, "
            f"or push removed_in out in dev10x.domain.deprecations (ADR-0028)."
        )

    @pytest.mark.parametrize("entry", REGISTER, ids=_entry_id)
    def test_removal_follows_the_audience_window(self, entry: Deprecation) -> None:
        _, since_minor, _ = parse_release(entry.since)
        _, removed_minor, _ = parse_release(entry.removed_in)
        counted_from = max(since_minor, REGISTER_LANDED_MINOR)

        assert removed_minor >= counted_from + max(WINDOW_MINOR_VERSIONS[entry.audience], 1)

    @pytest.mark.parametrize("path", _files_carrying_a_shim_marker())
    def test_marked_shim_is_registered(self, path: str) -> None:
        assert path in _registered_locations(), (
            f"{path} carries a deprecation marker but no dev10x.domain.deprecations "
            f"entry names it. Register the shim with a removal version (ADR-0028)."
        )

    @pytest.mark.parametrize(
        ("name", "location"),
        [(entry.name, location) for entry in REGISTER for location in entry.locations],
    )
    def test_registered_location_still_names_its_shim(self, name: str, location: str) -> None:
        assert name in (REPO_ROOT / location).read_text()

    def test_no_source_still_promises_one_release(self) -> None:
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "src").rglob("*.py")
            if re.search(r"for\W+one\s+release", path.read_text(), re.IGNORECASE)
        ]

        assert offenders == []
