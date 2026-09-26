"""The old ``dev10x.commands.github_app_api`` path keeps resolving (GH-1444)."""

from __future__ import annotations

import pytest

from dev10x.commands import github_app_api as legacy
from dev10x.github import app_api


@pytest.mark.parametrize("name", legacy.__all__)
def test_legacy_path_re_exports_the_moved_object(name: str) -> None:
    assert getattr(legacy, name) is getattr(app_api, name)
