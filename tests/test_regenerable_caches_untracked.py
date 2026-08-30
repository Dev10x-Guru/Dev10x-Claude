"""Keep derived config caches out of git (GH-1075).

``dev10x.config.loader.load_config`` derives a ``.msgpack`` cache from its
sibling YAML and rewrites it whenever the cache is missing or stale. While
``command-skill-map.msgpack`` was tracked, every test run, hook invocation, or
MCP call that loaded the config dirtied the working tree — so the cache was
swept into unrelated commits (``Dev10x:git-commit`` mandates ``git add -A``)
and produced a binary rebase conflict that has no meaningful resolution,
because the YAML is authoritative and the cache self-heals.

A tracked cache is easy to reintroduce: nothing about ``git add`` warns that a
generated file is being committed. This guard makes the invariant explicit —
every cache path the loader can derive must be both git-ignored and untracked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[1]

#: Directories whose YAML files ``load_config`` reads, and therefore whose
#: sibling ``.msgpack`` caches it writes.
_CACHED_CONFIG_DIRS: tuple[str, ...] = ("src/dev10x/validators",)

#: The suffix ``load_config`` swaps onto the YAML path to locate the cache.
_CACHE_SUFFIX = ".msgpack"


def _derived_cache_paths() -> list[Path]:
    return sorted(
        yaml_path.with_suffix(_CACHE_SUFFIX)
        for directory in _CACHED_CONFIG_DIRS
        for yaml_path in (_REPO_ROOT / directory).glob("*.yaml")
    )


def _is_tracked(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(_REPO_ROOT))],
        cwd=_REPO_ROOT,
        capture_output=True,
        timeout=30,
    )
    return completed.returncode == 0


def _is_ignored(path: Path) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(_REPO_ROOT))],
        cwd=_REPO_ROOT,
        capture_output=True,
        timeout=30,
    )
    return completed.returncode == 0


class TestDerivedCachesAreNotTracked:
    def test_scan_covers_the_cache_that_regressed(self) -> None:
        """Fail loud if the glob stops reaching the GH-1075 defect site."""
        regressed = _REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.msgpack"
        assert regressed in _derived_cache_paths()

    @pytest.mark.parametrize("cache_path", _derived_cache_paths(), ids=lambda p: p.name)
    def test_cache_is_untracked(self, cache_path: Path) -> None:
        assert not _is_tracked(cache_path), (
            f"{cache_path.relative_to(_REPO_ROOT)} is a cache dev10x.config.loader "
            "rewrites on its own, so tracking it dirties the tree on every load and "
            "makes rebases conflict on a binary file. Run "
            f"`git rm --cached {cache_path.relative_to(_REPO_ROOT)}`."
        )

    @pytest.mark.parametrize("cache_path", _derived_cache_paths(), ids=lambda p: p.name)
    def test_cache_is_git_ignored(self, cache_path: Path) -> None:
        assert _is_ignored(cache_path), (
            f"{cache_path.relative_to(_REPO_ROOT)} is untracked but not ignored, so it "
            "shows up as an unstaged addition after any config load. Add it to "
            ".gitignore."
        )
