"""Staleness sweep over declared dependency pins (GH-937).

Companion to `tests/test_dependency_pins.py` (the GH-916 upper-bound
lint). Every test injects a stub fetcher — the sweep never reaches PyPI
under pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.dependency_pins import (
    PinnedRequirement,
    collect_pinned_requirements,
    find_pinned_pep723_requirements,
    find_pinned_pyproject_requirements,
)
from dev10x.dependency_sweep import (
    UpperBound,
    exceeds_bound,
    fetch_latest_version,
    format_report,
    parse_release,
    sweep,
    upper_bound,
)
from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'dependencies = ["click>=8.0,<9", "pyjwt[crypto]>=2.8,<3"]\n\n'
        "[project.optional-dependencies]\n"
        'dev = ["pytest>=8.0,<9"]\n'
    )
    (tmp_path / "server.py").write_text('# dependencies = ["mcp>=1.0,<2", "click>=8.0,<9"]\n')
    return tmp_path


def stub_fetch(versions: dict[str, str]):
    def fetch(distribution: str) -> SuccessResult[str] | ErrorResult:
        if distribution not in versions:
            return err(f"no stub version for {distribution}")
        return ok(versions[distribution])

    return fetch


def test_pinned_pep723_requirements_carry_their_source(tmp_path: Path) -> None:
    script = tmp_path / "server.py"
    script.write_text('# dependencies = ["mcp>=1.0,<2", "unbounded"]\n')

    pinned = find_pinned_pep723_requirements(path=script, root=tmp_path)

    assert pinned == [
        PinnedRequirement(name="mcp", specifier=">=1.0,<2", source="server.py:1"),
    ]


def test_pinned_pyproject_requirements_cover_extras_and_sections(repo: Path) -> None:
    pinned = find_pinned_pyproject_requirements(path=repo / "pyproject.toml", root=repo)

    assert [(pin.name, pin.source) for pin in pinned] == [
        ("click", "pyproject.toml: [project.dependencies]"),
        ("pyjwt[crypto]", "pyproject.toml: [project.dependencies]"),
        ("pytest", "pyproject.toml: [project.optional-dependencies.dev]"),
    ]


def test_pinned_pyproject_requirements_skip_non_pyproject_files(tmp_path: Path) -> None:
    other = tmp_path / "other.toml"
    other.write_text('[project]\ndependencies = ["click>=8.0,<9"]\n')

    assert find_pinned_pyproject_requirements(path=other, root=tmp_path) == []


def test_extras_are_stripped_for_the_index_lookup() -> None:
    pin = PinnedRequirement(name="pyjwt[crypto]", specifier=">=2.8,<3", source="x")

    assert pin.distribution == "pyjwt"


def test_collect_pinned_requirements_walks_the_whole_tree(repo: Path) -> None:
    distributions = {pin.distribution for pin in collect_pinned_requirements(repo)}

    assert distributions == {"click", "pyjwt", "pytest", "mcp"}


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("7", (7,)),
        ("6.0.2", (6, 0, 2)),
        ("7.0rc1", (7, 0)),
        ("2.1.*", (2, 1)),
        ("dev", ()),
    ],
)
def test_parse_release(version: str, expected: tuple[int, ...]) -> None:
    assert parse_release(version) == expected


@pytest.mark.parametrize(
    ("specifier", "expected"),
    [
        (">=6.0,<7", UpperBound(operator="<", version="7")),
        (">=6.0,<=7.2", UpperBound(operator="<=", version="7.2")),
        ("==1.9.4", UpperBound(operator="==", version="1.9.4")),
        (">=1.0,<3,<2", UpperBound(operator="<", version="2")),
        (">=1.0,<2; python_version<'3.12'", UpperBound(operator="<", version="2")),
        (">=1.0", None),
    ],
)
def test_upper_bound(specifier: str, expected: UpperBound | None) -> None:
    assert upper_bound(specifier) == expected


def test_upper_bound_prefers_the_exclusive_form_at_the_same_release() -> None:
    assert upper_bound(">=1.0,<=2,<2") == UpperBound(operator="<", version="2")


@pytest.mark.parametrize(
    ("latest", "bound", "expected"),
    [
        ("6.0.2", UpperBound(operator="<", version="7"), False),
        ("7.0.1", UpperBound(operator="<", version="7"), True),
        ("7", UpperBound(operator="<=", version="7.2"), False),
        ("7.3", UpperBound(operator="<=", version="7.2"), True),
        ("1.9.4", UpperBound(operator="==", version="1.9.4"), False),
        ("1.9.5", UpperBound(operator="==", version="1.9.4"), True),
        ("unparseable", UpperBound(operator="<", version="7"), False),
    ],
)
def test_exceeds_bound(latest: str, bound: UpperBound, expected: bool) -> None:
    assert exceeds_bound(latest=latest, bound=bound) is expected


def test_sweep_reports_only_out_of_bounds_pins(repo: Path) -> None:
    result = sweep(
        root=repo,
        fetch=stub_fetch({"click": "8.1.7", "pyjwt": "2.9.0", "pytest": "8.3.3", "mcp": "2.0.1"}),
    )

    assert isinstance(result, SuccessResult)
    report = result.value
    assert [entry["distribution"] for entry in report["stale"]] == ["mcp"]
    assert report["stale"][0]["latest"] == "2.0.1"
    assert report["stale"][0]["bound"] == "<2"
    assert report["errors"] == []


def test_sweep_groups_duplicate_pins_into_one_lookup(repo: Path) -> None:
    calls: list[str] = []

    def counting_fetch(distribution: str) -> SuccessResult[str] | ErrorResult:
        calls.append(distribution)
        return ok("99.0")

    result = sweep(root=repo, fetch=counting_fetch)

    assert isinstance(result, SuccessResult)
    # click is declared identically in pyproject and server.py — one lookup.
    assert calls.count("click") == 1
    click_entry = next(
        entry for entry in result.value["stale"] if entry["distribution"] == "click"
    )
    assert click_entry["sources"] == [
        "pyproject.toml: [project.dependencies]",
        "server.py:1",
    ]


def test_sweep_records_a_lookup_failure_without_aborting(repo: Path) -> None:
    result = sweep(root=repo, fetch=stub_fetch({"click": "99.0"}))

    assert isinstance(result, SuccessResult)
    assert [entry["distribution"] for entry in result.value["stale"]] == ["click"]
    assert len(result.value["errors"]) == 3


def test_sweep_rejects_a_missing_root(tmp_path: Path) -> None:
    result = sweep(root=tmp_path / "absent", fetch=stub_fetch({}))

    assert isinstance(result, ErrorResult)
    assert "not a directory" in result.error


def test_sweep_surfaces_a_pin_with_no_parseable_ceiling(tmp_path: Path) -> None:
    # `==` with a non-numeric version is bounded to the lint but has no
    # comparable release — the sweep must report, not silently drop it.
    (tmp_path / "server.py").write_text('# dependencies = ["foo==nightly"]\n')

    result = sweep(root=tmp_path, fetch=stub_fetch({}))

    assert isinstance(result, SuccessResult)
    assert result.value["stale"] == []
    assert result.value["errors"] == ["No parseable upper bound in foo==nightly"]


def test_format_report_says_nothing_is_stale() -> None:
    rendered = format_report({"pins": 4, "distributions": 4, "stale": [], "errors": []})

    assert "No pinned dependency" in rendered
    assert "Checked 4 pinned requirement(s)" in rendered


def test_format_report_lists_stale_pins_and_errors() -> None:
    rendered = format_report(
        {
            "pins": 2,
            "distributions": 2,
            "stale": [
                {
                    "distribution": "mcp",
                    "specifier": ">=1.0,<2",
                    "bound": "<2",
                    "latest": "2.0.1",
                    "sources": ["servers/cli_server.py:5"],
                }
            ],
            "errors": ["PyPI returned HTTP 404 for typo-pkg"],
        }
    )

    assert "**mcp**" in rendered
    assert "`servers/cli_server.py:5`" in rendered
    assert "Lookup errors" in rendered


def test_fetch_latest_version_reads_info_version(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def read(self) -> bytes:
            return b'{"info": {"version": "8.1.7"}}'

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: FakeResponse(),
    )

    assert fetch_latest_version("click") == ok("8.1.7")


def test_fetch_latest_version_reports_a_missing_version(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def read(self) -> bytes:
            return b"{}"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: FakeResponse(),
    )

    result = fetch_latest_version("click")

    assert isinstance(result, ErrorResult)
    assert "info.version" in result.error


def test_fetch_latest_version_reports_an_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def raising(request: object, timeout: float | None = None) -> None:
        raise urllib.error.HTTPError(url="u", code=404, msg="nf", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", raising)

    result = fetch_latest_version("nope")

    assert isinstance(result, ErrorResult)
    assert "HTTP 404" in result.error


def test_fetch_latest_version_reports_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def raising(request: object, timeout: float | None = None) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", raising)

    result = fetch_latest_version("click")

    assert isinstance(result, ErrorResult)
    assert "request failed" in result.error


def test_fetch_latest_version_reports_an_unreadable_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def read(self) -> bytes:
            return b"not json"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: FakeResponse(),
    )

    result = fetch_latest_version("click")

    assert isinstance(result, ErrorResult)
    assert "unreadable payload" in result.error
