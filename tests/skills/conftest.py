from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_dir(tmp_path: Path) -> Path:
    fake = tmp_path / "fake"
    fake.mkdir()
    return fake
