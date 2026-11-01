"""Skill-name migration for user configs (ADR-0034 Stage A4, GH-1559).

Every test writes under ``tmp_path``; the root conftest also points
``DEV10X_CONFIG_HOME`` at a tmp directory, so the real
``~/.config/Dev10x`` is never read or written.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.core.domain.deprecations import REGISTER
from dev10x.core.domain.file_locks import LockTimeoutError
from dev10x.core.plugin_map import load_plugin_map
from dev10x.core.skills.upgrade_cleanup import skill_names
from dev10x.core.skills.upgrade_cleanup.skill_names import (
    SKILL_NAME_ALIASES,
    ConfigRewrite,
    SkillNameAlias,
    aliases_outliving,
    migrate_text,
    migrate_user_configs,
    resolve_skill_alias,
    user_config_files,
)

GOG_ALIAS = SkillNameAlias(old="dev10x:gog", new="dev10x-comm:gog", removed_in="0.114.0")
ALIASES = (GOG_ALIAS,)

FRICTION = "defaults:\n  skill: dev10x:gog  # chosen by hand\n"
DOD = "criteria:\n  - check: Skill(Dev10x:gog)\n  - check: dev10x:git\n"
PLAYBOOK = "steps:\n  - skill: dev10x:gog\n"
UNTOUCHED = "dev10x:gog\n"


@pytest.fixture
def config_home(tmp_path: Path) -> Path:
    home = tmp_path / "config-home"
    (home / "playbooks").mkdir(parents=True)
    (home / "friction.yaml").write_text(FRICTION)
    (home / "dod-acceptance-criteria.yaml").write_text(DOD)
    (home / "playbooks" / "work-on.yaml").write_text(PLAYBOOK)
    (home / "playbooks" / "notes.txt").write_text(UNTOUCHED)
    (home / "projects.yaml").write_text(UNTOUCHED)
    return home


@pytest.fixture
def applied(config_home: Path) -> list[ConfigRewrite]:
    result = migrate_user_configs(config_home=config_home, aliases=ALIASES, dry_run=False)
    assert isinstance(result, SuccessResult)
    return result.value


def _texts(*, home: Path) -> dict[str, str]:
    return {
        path.relative_to(home).as_posix(): path.read_text()
        for path in sorted(home.rglob("*"))
        if path.is_file() and path.suffix != ".lock"
    }


class TestUserConfigFiles:
    def test_lists_friction_dod_and_playbook_overrides(self, config_home: Path) -> None:
        assert user_config_files(config_home=config_home) == [
            config_home / "friction.yaml",
            config_home / "dod-acceptance-criteria.yaml",
            config_home / "playbooks" / "work-on.yaml",
        ]

    def test_missing_home_lists_nothing(self, tmp_path: Path) -> None:
        assert user_config_files(config_home=tmp_path / "absent") == []


class TestMigrateText:
    def test_rewrites_every_alias_and_keeps_comments(self) -> None:
        assert migrate_text(text=FRICTION, aliases=ALIASES) == (
            "defaults:\n  skill: dev10x-comm:gog  # chosen by hand\n",
            1,
        )

    def test_chained_aliases_land_on_the_last_name(self) -> None:
        chain = (
            GOG_ALIAS,
            SkillNameAlias(old="dev10x-comm:gog", new="dev10x-comm:gogs", removed_in="0.114.0"),
        )

        assert migrate_text(text="dev10x:gog", aliases=chain) == ("dev10x-comm:gogs", 2)


class TestMigrateUserConfigs:
    def test_dry_run_reports_without_writing(self, config_home: Path) -> None:
        before = _texts(home=config_home)

        result = migrate_user_configs(config_home=config_home, aliases=ALIASES, dry_run=True)

        assert result == SuccessResult(
            value=[
                ConfigRewrite(path=config_home / "friction.yaml", replacements=1),
                ConfigRewrite(path=config_home / "dod-acceptance-criteria.yaml", replacements=1),
                ConfigRewrite(path=config_home / "playbooks" / "work-on.yaml", replacements=1),
            ]
        )
        assert _texts(home=config_home) == before

    def test_apply_rewrites_the_fixture_config(
        self,
        config_home: Path,
        applied: list[ConfigRewrite],
    ) -> None:
        assert _texts(home=config_home) == {
            "dod-acceptance-criteria.yaml": (
                "criteria:\n  - check: Skill(Dev10x-comm:gog)\n  - check: dev10x:git\n"
            ),
            "friction.yaml": "defaults:\n  skill: dev10x-comm:gog  # chosen by hand\n",
            "playbooks/notes.txt": UNTOUCHED,
            "playbooks/work-on.yaml": "steps:\n  - skill: dev10x-comm:gog\n",
            "projects.yaml": UNTOUCHED,
        }

    def test_second_run_is_a_no_op(self, config_home: Path, applied: list[ConfigRewrite]) -> None:
        after_first = _texts(home=config_home)

        second = migrate_user_configs(config_home=config_home, aliases=ALIASES, dry_run=False)

        assert (second, _texts(home=config_home)) == (SuccessResult(value=[]), after_first)

    def test_lock_timeout_is_reported(
        self,
        config_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        @contextmanager
        def wedged(path: Path) -> Iterator[None]:
            raise LockTimeoutError("lock held")
            yield

        monkeypatch.setattr(skill_names, "file_lock", wedged)

        result = migrate_user_configs(config_home=config_home, aliases=ALIASES, dry_run=False)

        assert isinstance(result, ErrorResult)
        assert result.error.endswith("friction.yaml: lock held. Please try again.")


class TestAliasResolution:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("dev10x:gog", "dev10x-comm:gog"),
            ("dev10x-comm:gog", "dev10x-comm:gog"),
            ("dev10x:git", "dev10x:git"),
        ],
    )
    def test_old_name_resolves_to_new(self, name: str, expected: str) -> None:
        assert resolve_skill_alias(name=name, aliases=ALIASES) == expected

    def test_shipped_table_resolves_every_name_to_itself(self) -> None:
        assert resolve_skill_alias(name="dev10x:gog") == "dev10x:gog"


class TestRegister:
    @pytest.fixture
    def entry_removed_in(self) -> str:
        return {entry.name: entry for entry in REGISTER}["SKILL_NAME_ALIASES"].removed_in

    def test_shipped_aliases_rewrite_a_moved_qa_name(self) -> None:
        assert migrate_text(
            text="steps:\n  - skill: dev10x:qa-self\n", aliases=SKILL_NAME_ALIASES
        ) == ("steps:\n  - skill: dev10x-qa:qa-self\n", 1)

    def test_every_extracted_skill_keeps_its_old_name_as_an_alias(self) -> None:
        plugin_map = load_plugin_map()
        expected = {
            (f"dev10x:{skill}", f"{plugin_map.plugin_name(key=key)}:{skill}")
            for key in plugin_map.extracted
            for skill in plugin_map.plugins[key]
        }

        assert {(alias.old, alias.new) for alias in SKILL_NAME_ALIASES} == expected

    def test_no_shipped_alias_outlives_the_register_entry(self, entry_removed_in: str) -> None:
        assert aliases_outliving(aliases=SKILL_NAME_ALIASES, removed_in=entry_removed_in) == []

    def test_flags_an_alias_that_outlives_the_entry(self) -> None:
        late = SkillNameAlias(old="dev10x:tts", new="dev10x-qa:tts", removed_in="0.120.0")

        assert aliases_outliving(aliases=(GOG_ALIAS, late), removed_in="0.114.0") == ["dev10x:tts"]
