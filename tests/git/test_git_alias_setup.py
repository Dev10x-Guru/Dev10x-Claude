"""Branch-comparison aliases resolve against origin (GH-1281).

``{base}-log`` / ``-diff`` / ``-rebase`` computed their merge-base against
the LOCAL base ref. A `develop` last pulled hours ago sits behind origin,
which moves the merge-base backwards and folds every commit merged since
into the branch's own diff — one session reviewed 36 changed files where
18 had actually changed. ``autosquash-{base}`` was already written the
correct way, so the two families disagreed about what "since the base"
meant.

The installer is run against a throwaway ``GIT_CONFIG_GLOBAL`` so the
upgrade path can be driven end to end: the pre-fix definitions are
written first, exactly as an earlier version of the script wrote them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).parents[2] / "skills" / "git-alias-setup" / "scripts" / "git-alias-setup.sh"
)
_TIMEOUT_SECONDS = 30

_COMPARISON_BASES = ("develop", "development", "trunk", "main", "master")
_COMPARISON_SUFFIXES = ("log", "diff", "rebase")

# GIT_CONFIG_GLOBAL replaces ~/.gitconfig outright from git 2.32. On an
# older binary these tests would read and write the developer's real
# global config and still pass, so the precondition is asserted rather
# than assumed — a silently-polluted ~/.gitconfig is the one outcome
# worth failing loudly over.
_MIN_GIT_FOR_CONFIG_ISOLATION = (2, 32)


def _git_version() -> tuple[int, ...]:
    out = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=_TIMEOUT_SECONDS,
    ).stdout.split()[2]
    return tuple(int(part) for part in out.split(".")[:2] if part.isdigit())


pytestmark = pytest.mark.skipif(
    _git_version() < _MIN_GIT_FOR_CONFIG_ISOLATION,
    reason="GIT_CONFIG_GLOBAL only replaces ~/.gitconfig from git 2.32",
)


@pytest.fixture()
def global_config(tmp_path: Path) -> Path:
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    return config


def _run_installer(*, config: Path) -> str:
    result = subprocess.run(
        [str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_SYSTEM": os.devnull},
        timeout=_TIMEOUT_SECONDS,
    )
    return result.stdout


def _alias(name: str, *, config: Path) -> str:
    return subprocess.run(
        ["git", "config", "--global", "--get", f"alias.{name}"],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_SYSTEM": os.devnull},
        timeout=_TIMEOUT_SECONDS,
    ).stdout.strip()


def _set_alias(name: str, value: str, *, config: Path) -> None:
    subprocess.run(
        ["git", "config", "--global", f"alias.{name}", value],
        check=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_SYSTEM": os.devnull},
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize("base", _COMPARISON_BASES)
@pytest.mark.parametrize("suffix", _COMPARISON_SUFFIXES)
class TestFreshInstall:
    def test_the_merge_base_is_qualified(
        self,
        base: str,
        suffix: str,
        global_config: Path,
    ) -> None:
        _run_installer(config=global_config)

        assert f"merge-base origin/{base} HEAD" in _alias(f"{base}-{suffix}", config=global_config)

    def test_no_bare_local_ref_survives(
        self,
        base: str,
        suffix: str,
        global_config: Path,
    ) -> None:
        # The positive assertion above would still pass if the alias
        # mentioned both spellings.
        _run_installer(config=global_config)

        assert f"merge-base {base} HEAD" not in _alias(f"{base}-{suffix}", config=global_config)


class TestUpgradeFromASupersededDefinition:
    """The fix must reach machines that already ran the old script."""

    def test_a_superseded_definition_is_rewritten(self, global_config: Path) -> None:
        _set_alias(
            "develop-diff",
            "!git diff $(git merge-base develop HEAD)..HEAD",
            config=global_config,
        )

        _run_installer(config=global_config)

        assert "merge-base origin/develop HEAD" in _alias("develop-diff", config=global_config)

    def test_the_rewrite_is_reported(self, global_config: Path) -> None:
        _set_alias(
            "develop-diff",
            "!git diff $(git merge-base develop HEAD)..HEAD",
            config=global_config,
        )

        assert "updated" in _run_installer(config=global_config)

    def test_a_user_definition_is_left_alone(self, global_config: Path) -> None:
        # Anything that is neither the current nor the superseded spelling
        # belongs to the user; overwriting it would be the more damaging
        # failure of the two.
        mine = "!git diff --stat @{upstream}..HEAD"
        _set_alias("develop-diff", mine, config=global_config)

        _run_installer(config=global_config)

        assert _alias("develop-diff", config=global_config) == mine

    def test_a_user_definition_is_reported_as_untouched(self, global_config: Path) -> None:
        _set_alias("develop-diff", "!git diff --stat @{upstream}..HEAD", config=global_config)

        assert "customized" in _run_installer(config=global_config)

    def test_a_current_definition_is_not_rewritten(self, global_config: Path) -> None:
        _run_installer(config=global_config)

        assert "already configured" in _run_installer(config=global_config)


@pytest.mark.parametrize("base", _COMPARISON_BASES)
class TestBothFamiliesAgree:
    """The divergence between the two families IS GH-1281.

    Checking one base would let a later edit reintroduce it on another,
    which is exactly how the bug arrived: `autosquash-*` was authored
    separately from `-log`/`-diff`/`-rebase` and stayed correct while
    the others drifted, with nothing asserting they agreed.
    """

    def test_autosquash_and_rebase_resolve_against_the_same_ref(
        self,
        base: str,
        global_config: Path,
    ) -> None:
        _run_installer(config=global_config)

        autosquash = _alias(f"autosquash-{base}", config=global_config)
        rebase = _alias(f"{base}-rebase", config=global_config)
        assert f"merge-base origin/{base} HEAD" in autosquash
        assert f"merge-base origin/{base} HEAD" in rebase

    def test_every_alias_in_the_family_exists(
        self,
        base: str,
        global_config: Path,
    ) -> None:
        # Generating the array could silently drop a name; the aliases
        # are a published interface other skills call by name.
        _run_installer(config=global_config)

        names = [f"{base}-{suffix}" for suffix in _COMPARISON_SUFFIXES]
        names.append(f"autosquash-{base}")
        assert all(_alias(name, config=global_config) for name in names)
