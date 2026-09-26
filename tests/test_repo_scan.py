"""Tests for the shared repo-walker (GH-1460).

`dev10x.subprocess_timeouts` and `dev10x.dependency_pins` both delegate
their `scanned_files` to `walk_repository` here — this file covers the
walker directly so the two detector test suites don't have to re-prove
its exclusion/symlink/suffix behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.repo_scan import SKIPPED_DIRS, walk_repository


def test_returns_files_matching_the_given_suffixes(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.toml").write_text("")
    (tmp_path / "c.txt").write_text("")

    found = walk_repository(tmp_path, suffixes={".py", ".toml"})

    assert found == sorted([tmp_path / "a.py", tmp_path / "b.toml"])


def test_single_suffix_caller_only_sees_that_suffix(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.sh").write_text("")

    found = walk_repository(tmp_path, suffixes={".py"})

    assert found == [tmp_path / "a.py"]


@pytest.mark.parametrize("skipped", sorted(SKIPPED_DIRS))
def test_skips_every_excluded_directory(tmp_path: Path, skipped: str) -> None:
    nested = tmp_path / skipped / "nested.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("")

    assert walk_repository(tmp_path, suffixes={".py"}) == []


def test_excludes_symlinked_files(tmp_path: Path) -> None:
    real = tmp_path / "real.py"
    real.write_text("")
    link = tmp_path / "link.py"
    link.symlink_to(real)

    found = walk_repository(tmp_path, suffixes={".py"})

    assert found == [real]


def test_returns_sorted_results(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("")
    (tmp_path / "a.py").write_text("")

    found = walk_repository(tmp_path, suffixes={".py"})

    assert found == sorted(found)
