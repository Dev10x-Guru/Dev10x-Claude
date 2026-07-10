import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from factory.random import reseed_random

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.dev10x_paths import CONFIG_HOME_ENV_VAR, Dev10xConfigDir

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_root_magicmock_files() -> set[Path]:
    return {entry for entry in _REPO_ROOT.iterdir() if entry.name.startswith("<MagicMock")}


def _real_repo_head() -> str | None:
    """HEAD SHA of the real repository this test session runs in.

    Returns None when git is unavailable or _REPO_ROOT is not a checkout,
    so the guard degrades to a no-op rather than erroring.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _guard_real_repo_head_unchanged() -> Generator[None, None, None]:
    """Fail the test if it moves the real repository's HEAD (GH-699).

    A git rebase/reset whose cwd defaults to the real repo — instead of a
    ``tmp_path`` sandbox — silently rewinds the branch under test and can
    drop a commit before a push (observed dropping a commit twice while
    shipping PR #698). Snapshot HEAD around every test; if it moved, move
    the branch pointer back with ``reset --soft`` (restores the dropped tip
    without touching the working tree, so local WIP is never clobbered) and
    fail loudly naming the offending test so its unsandboxed git call can be
    given ``cwd=tmp_path``.
    """
    before = _real_repo_head()
    yield
    after = _real_repo_head()
    if before is None or after is None or before == after:
        return
    subprocess.run(
        ["git", "reset", "--soft", before],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    pytest.fail(
        f"Test rewound the real repo HEAD {before[:12]} -> {after[:12]} "
        "(GH-699): a git rebase/reset ran against the real repository "
        "instead of a tmp_path sandbox. The branch pointer was restored; "
        "sandbox the offending git invocation with cwd=tmp_path.",
        pytrace=False,
    )


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
def _isolate_dev10x_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    """Point Dev10xConfigDir at an isolated tmp home (ADR-0018).

    Durable session prefs now read the global ``~/.config/Dev10x/friction.yaml``
    transitively via ``SessionYamlDocument._durable()``, and ``dev10x init`` /
    ``dev10x session seed`` write it. Without isolation every session-config
    test would read — and those commands would write — the developer's real
    ``~/.config/Dev10x``. Tests that exercise default-root resolution override
    this with their own ``monkeypatch.delenv`` (see ``test_dev10x_paths``).
    """
    monkeypatch.setenv(CONFIG_HOME_ENV_VAR, str(tmp_path / "dev10x-config-home"))
    Dev10xConfigDir.reset_cache()
    yield
    Dev10xConfigDir.reset_cache()


@pytest.fixture(autouse=True)
def _seed_factory_faker() -> None:
    """Reseed factory_boy's Faker before each test so generated values are
    deterministic and a value-specific failure is reproducible (GH-570)."""
    reseed_random("dev10x-tests")
