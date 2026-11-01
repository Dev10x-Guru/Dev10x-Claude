"""Tests for supervisor state paths per instance (GH-1765)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dev10x.comm.supervisor import paths

PathFn = Callable[..., Path]


@pytest.mark.parametrize(
    ("instance", "expected"),
    [
        (
            paths.Instance.RELEASE,
            paths.InstanceProfile(
                default_port=8765, keeps_page_token=False, renames_sessions=True
            ),
        ),
        (
            paths.Instance.DEV,
            paths.InstanceProfile(
                default_port=8766, keeps_page_token=True, renames_sessions=False
            ),
        ),
    ],
    ids=["release", "dev"],
)
def test_profile(instance: paths.Instance, expected: paths.InstanceProfile) -> None:
    assert paths.profile(instance=instance) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [("tok\n", "tok"), ("  \n", "")],
    ids=["saved", "blank"],
)
def test_read_token(tmp_path: Path, content: str, expected: str) -> None:
    path = tmp_path / "token"
    path.write_text(content, encoding="utf-8")

    assert paths.read_token(path=path) == expected


def test_read_token_missing_file(tmp_path: Path) -> None:
    assert paths.read_token(path=tmp_path / "gone") == ""


@pytest.mark.parametrize(
    ("path_fn", "name"),
    [
        (paths.token_path, "token"),
        (paths.page_token_path, "page-token"),
        (paths.decisions_path, "decisions.json"),
        (paths.settings_path, "settings.json"),
        (paths.actions_log_path, "actions.jsonl"),
    ],
    ids=["token", "page-token", "decisions", "settings", "actions"],
)
class TestInstancePaths:
    def test_release_keeps_the_original_dir(
        self, config_home: Path, path_fn: PathFn, name: str
    ) -> None:
        assert path_fn() == config_home / "supervisor" / name

    def test_dev_lives_in_its_own_subdir(
        self, config_home: Path, path_fn: PathFn, name: str
    ) -> None:
        assert path_fn(instance=paths.Instance.DEV) == config_home / "supervisor" / "dev" / name
