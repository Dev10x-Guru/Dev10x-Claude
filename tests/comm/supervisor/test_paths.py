"""Tests for supervisor state paths per instance (GH-1765)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from dev10x.comm.supervisor import paths

PathFn = Callable[..., Path]


@pytest.mark.parametrize(
    ("instance", "port"),
    [(paths.Instance.RELEASE, 8765), (paths.Instance.DEV, 8766)],
    ids=["release", "dev"],
)
def test_default_port(instance: paths.Instance, port: int) -> None:
    assert paths.default_port(instance=instance) == port


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
