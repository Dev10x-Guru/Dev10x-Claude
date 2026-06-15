from collections.abc import Generator
from pathlib import Path

import pytest
from factory.random import reseed_random

from dev10x.domain.claude_paths import ClaudeDir

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_root_magicmock_files() -> set[Path]:
    return {entry for entry in _REPO_ROOT.iterdir() if entry.name.startswith("<MagicMock")}


@pytest.fixture(scope="session", autouse=True)
def _guard_repo_root_magicmock_pollution() -> Generator[None, None, None]:
    """Fail the session if a test leaks a MagicMock-named file at repo root.

    When a mock's chained attribute (e.g. ``get_plan_path().with_suffix()``)
    is passed to ``os.open()``/``write_text()``, the write lands at the
    mock's repr, creating a literal ``<MagicMock name=... id=...>`` file in
    the CWD that pollutes ``git add -A``. Catch and remove any such files so
    they never reach a commit, then fail loudly so the offending mock is
    fixed at the source (GH-332).
    """
    before = _repo_root_magicmock_files()
    yield
    leaked = sorted(entry for entry in _repo_root_magicmock_files() if entry not in before)
    for entry in leaked:
        entry.unlink()
    assert not leaked, (
        "Tests leaked MagicMock-named files at repo root (GH-332): "
        f"{[entry.name for entry in leaked]}. A MagicMock was passed to a "
        "file-write; configure the path mock to return a real tmp_path."
    )


@pytest.fixture(autouse=True)
def _reset_claude_dir_cache() -> None:
    """Clear ClaudeDir's path cache to keep DEV10X_CLAUDE_HOME overrides isolated."""
    ClaudeDir.reset_cache()


@pytest.fixture(autouse=True)
def _seed_factory_faker() -> None:
    """Reseed factory_boy's Faker before each test so generated values are
    deterministic and a value-specific failure is reproducible (GH-570)."""
    reseed_random("dev10x-tests")
