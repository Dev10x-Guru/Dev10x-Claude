from __future__ import annotations

from typing import Any

import pytest

from tests.skills.playbook.play_expansion import load_work_on_playbook


@pytest.fixture(scope="session")
def playbook() -> dict[str, Any]:
    return load_work_on_playbook()
