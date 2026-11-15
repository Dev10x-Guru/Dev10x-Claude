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

    def test_shipped_table_leaves_a_core_name_alone(self) -> None:
        assert resolve_skill_alias(name="dev10x:afk") == "dev10x:afk"


MOVED_TO_COMM_IN_GH_1567 = (
    "bus",
    "gchat",
    "gog",
    "overwatch",
    "slack",
    "slack-setup",
    "voice-channel",
)


class TestCommExtractionAliases:
    @pytest.mark.parametrize("skill", MOVED_TO_COMM_IN_GH_1567)
    def test_old_name_resolves_to_the_comm_plugin(self, skill: str) -> None:
        assert resolve_skill_alias(name=f"dev10x:{skill}") == f"dev10x-comm:{skill}"

    def test_every_moved_skill_keeps_its_old_name_as_an_alias(self) -> None:
        plugin_map = load_plugin_map()

        assert {(alias.old, alias.new) for alias in SKILL_NAME_ALIASES} == {
            (f"dev10x:{skill}", f"{plugin_map.plugin_names[key]}:{skill}")
            for key in ("comm", "teach", "tasks", "scoping", "coding")
            for skill in plugin_map.plugins[key]
        }

    def test_rewrites_a_moved_name_in_a_user_playbook(self) -> None:
        assert migrate_text(
            text="steps:\n  - skill: dev10x:slack\n", aliases=SKILL_NAME_ALIASES
        ) == (
            "steps:\n  - skill: dev10x-comm:slack\n",
            1,
        )

    def test_sends_a_name_that_shares_a_prefix_to_its_own_plugin(self) -> None:
        text = "skill: dev10x:slack-review-request\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (
            "skill: dev10x-coding:slack-review-request\n",
            1,
        )

    @pytest.fixture
    def migrated_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "config-home"
        (home / "playbooks").mkdir(parents=True)
        (home / "friction.yaml").write_text("defaults:\n  notify: dev10x:gchat\n")
        (home / "playbooks" / "work-on.yaml").write_text(
            "steps:\n  - skill: dev10x:slack\n  - skill: dev10x:slack-review-request\n"
        )
        result = migrate_user_configs(config_home=home, dry_run=False)
        assert isinstance(result, SuccessResult)
        return home

    def test_shipped_table_migrates_a_temp_config_home(self, migrated_home: Path) -> None:
        assert _texts(home=migrated_home) == {
            "friction.yaml": "defaults:\n  notify: dev10x-comm:gchat\n",
            "playbooks/work-on.yaml": (
                "steps:\n  - skill: dev10x-comm:slack\n"
                "  - skill: dev10x-coding:slack-review-request\n"
            ),
        }


MOVED_TO_TEACH_IN_GH_1568 = (
    "audit-file",
    "context-audit",
    "memory-maintenance",
    "skill-audit",
    "skill-audit-queue",
    "skill-create",
    "skill-index",
)


class TestTeachExtractionAliases:
    @pytest.mark.parametrize("skill", MOVED_TO_TEACH_IN_GH_1568)
    def test_old_name_resolves_to_the_teach_plugin(self, skill: str) -> None:
        assert resolve_skill_alias(name=f"dev10x:{skill}") == f"dev10x-teach:{skill}"

    def test_rewrites_a_name_and_its_longer_sibling_separately(self) -> None:
        text = "skills:\n  - dev10x:skill-audit\n  - dev10x:skill-audit-queue\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (
            "skills:\n  - dev10x-teach:skill-audit\n  - dev10x-teach:skill-audit-queue\n",
            2,
        )

    def test_leaves_a_core_name_that_shares_a_prefix(self) -> None:
        text = "skill: dev10x:skill-prune\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (text, 0)

    @pytest.fixture
    def migrated_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "config-home"
        (home / "playbooks").mkdir(parents=True)
        (home / "friction.yaml").write_text("defaults:\n  audit: dev10x:skill-audit\n")
        (home / "playbooks" / "fanout.yaml").write_text(
            "steps:\n  - skill: dev10x:skill-audit-queue\n  - skill: dev10x:skill-prune\n"
        )
        result = migrate_user_configs(config_home=home, dry_run=False)
        assert isinstance(result, SuccessResult)
        return home

    def test_shipped_table_migrates_a_temp_config_home(self, migrated_home: Path) -> None:
        assert _texts(home=migrated_home) == {
            "friction.yaml": "defaults:\n  audit: dev10x-teach:skill-audit\n",
            "playbooks/fanout.yaml": (
                "steps:\n  - skill: dev10x-teach:skill-audit-queue\n"
                "  - skill: dev10x:skill-prune\n"
            ),
        }


MOVED_TO_TASKS_IN_GH_1569 = (
    "park",
    "park-discover",
    "park-remind",
    "park-todo",
    "plan-sync",
    "reflect",
    "session-tasks",
    "session-wrap-up",
)


class TestTasksExtractionAliases:
    @pytest.mark.parametrize("skill", MOVED_TO_TASKS_IN_GH_1569)
    def test_old_name_resolves_to_the_tasks_plugin(self, skill: str) -> None:
        assert resolve_skill_alias(name=f"dev10x:{skill}") == f"dev10x-tasks:{skill}"

    def test_rewrites_park_and_its_longer_siblings_separately(self) -> None:
        text = "skills:\n  - dev10x:park\n  - dev10x:park-todo\n  - dev10x:park-discover\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (
            "skills:\n  - dev10x-tasks:park\n  - dev10x-tasks:park-todo\n"
            "  - dev10x-tasks:park-discover\n",
            3,
        )

    def test_leaves_a_core_name_that_shares_a_prefix(self) -> None:
        text = "skill: dev10x:session-config-seed\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (text, 0)

    @pytest.fixture
    def migrated_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "config-home"
        (home / "playbooks").mkdir(parents=True)
        (home / "friction.yaml").write_text("defaults:\n  wrap_up: dev10x:session-wrap-up\n")
        (home / "playbooks" / "work-on.yaml").write_text(
            "steps:\n  - skill: dev10x:reflect\n  - skill: dev10x:session-config-seed\n"
        )
        result = migrate_user_configs(config_home=home, dry_run=False)
        assert isinstance(result, SuccessResult)
        return home

    def test_shipped_table_migrates_a_temp_config_home(self, migrated_home: Path) -> None:
        assert _texts(home=migrated_home) == {
            "friction.yaml": "defaults:\n  wrap_up: dev10x-tasks:session-wrap-up\n",
            "playbooks/work-on.yaml": (
                "steps:\n  - skill: dev10x-tasks:reflect\n  - skill: dev10x:session-config-seed\n"
            ),
        }


MOVED_TO_SCOPING_IN_GH_1570 = (
    "adr",
    "adr-evaluate",
    "artifact",
    "ddd",
    "diagram-bpmn",
    "diagram-c4",
    "diagram-sequence",
    "estimate",
    "jira",
    "jtbd",
    "linear",
    "project-audit",
    "project-scope",
    "scope",
    "spec-sync",
    "spec-update",
    "ticket-create",
    "ticket-jtbd",
    "ticket-scope",
)


class TestScopingExtractionAliases:
    @pytest.mark.parametrize("skill", MOVED_TO_SCOPING_IN_GH_1570)
    def test_old_name_resolves_to_the_scoping_plugin(self, skill: str) -> None:
        assert resolve_skill_alias(name=f"dev10x:{skill}") == f"dev10x-scoping:{skill}"

    def test_rewrites_names_that_share_a_suffix_separately(self) -> None:
        text = (
            "skills:\n  - dev10x:scope\n  - dev10x:ticket-scope\n  - dev10x:project-scope\n"
            "  - dev10x:jtbd\n  - dev10x:ticket-jtbd\n  - dev10x:adr\n  - dev10x:adr-evaluate\n"
        )

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (
            "skills:\n  - dev10x-scoping:scope\n  - dev10x-scoping:ticket-scope\n"
            "  - dev10x-scoping:project-scope\n  - dev10x-scoping:jtbd\n"
            "  - dev10x-scoping:ticket-jtbd\n  - dev10x-scoping:adr\n"
            "  - dev10x-scoping:adr-evaluate\n",
            7,
        )

    def test_sends_a_coding_name_that_shares_a_prefix_to_coding(self) -> None:
        text = "skill: dev10x:ticket-branch\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (
            "skill: dev10x-coding:ticket-branch\n",
            1,
        )

    @pytest.fixture
    def migrated_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "config-home"
        (home / "playbooks").mkdir(parents=True)
        (home / "friction.yaml").write_text("defaults:\n  scope: dev10x:ticket-scope\n")
        (home / "playbooks" / "work-on.yaml").write_text(
            "steps:\n  - skill: dev10x:ticket-create\n  - skill: dev10x:ticket-branch\n"
        )
        (home / "dod-acceptance-criteria.yaml").write_text("- skill: dev10x:spec-sync\n")
        result = migrate_user_configs(config_home=home, dry_run=False)
        assert isinstance(result, SuccessResult)
        return home

    def test_shipped_table_migrates_a_temp_config_home(self, migrated_home: Path) -> None:
        assert _texts(home=migrated_home) == {
            "friction.yaml": "defaults:\n  scope: dev10x-scoping:ticket-scope\n",
            "dod-acceptance-criteria.yaml": "- skill: dev10x-scoping:spec-sync\n",
            "playbooks/work-on.yaml": (
                "steps:\n  - skill: dev10x-scoping:ticket-create\n"
                "  - skill: dev10x-coding:ticket-branch\n"
            ),
        }


MOVED_TO_CODING_IN_GH_1572 = (
    "ci-review",
    "fanout",
    "foreman",
    "gchat-review-request",
    "gh-pr-bookmark",
    "gh-pr-create",
    "gh-pr-doctor",
    "gh-pr-fixup",
    "gh-pr-merge",
    "gh-pr-monitor",
    "gh-pr-request-review",
    "gh-pr-respond",
    "gh-pr-review",
    "gh-pr-triage",
    "gh-review-setup",
    "git",
    "git-alias-setup",
    "git-branch-prune",
    "git-commit",
    "git-commit-split",
    "git-fixup",
    "git-groom",
    "git-promote",
    "git-worktree",
    "git-worktree-prune",
    "ide-normalize",
    "investigate",
    "py-mockito",
    "py-test",
    "py-test-flaky",
    "py-uv",
    "qa-scope",
    "release-notes",
    "request-review",
    "review",
    "review-fix",
    "slack-review-request",
    "ticket-branch",
    "verify-acc-dod",
    "work-on",
)


class TestCodingExtractionAliases:
    @pytest.mark.parametrize("skill", MOVED_TO_CODING_IN_GH_1572)
    def test_old_name_resolves_to_the_coding_plugin(self, skill: str) -> None:
        assert resolve_skill_alias(name=f"dev10x:{skill}") == f"dev10x-coding:{skill}"

    def test_rewrites_git_and_its_longer_siblings_separately(self) -> None:
        text = (
            "skills:\n  - dev10x:git\n  - dev10x:git-commit\n  - dev10x:git-worktree-prune\n"
            "  - dev10x:review\n  - dev10x:review-fix\n"
        )

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (
            "skills:\n  - dev10x-coding:git\n  - dev10x-coding:git-commit\n"
            "  - dev10x-coding:git-worktree-prune\n  - dev10x-coding:review\n"
            "  - dev10x-coding:review-fix\n",
            5,
        )

    def test_leaves_a_core_name_that_shares_a_prefix(self) -> None:
        text = "skill: dev10x:playbook-maintenance\n"

        assert migrate_text(text=text, aliases=SKILL_NAME_ALIASES) == (text, 0)

    @pytest.fixture
    def migrated_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "config-home"
        (home / "playbooks").mkdir(parents=True)
        (home / "friction.yaml").write_text("defaults:\n  commit: dev10x:git-commit\n")
        (home / "playbooks" / "work-on.yaml").write_text(
            "steps:\n  - skill: dev10x:gh-pr-create\n  - skill: dev10x:playbook\n"
        )
        (home / "dod-acceptance-criteria.yaml").write_text("- skill: dev10x:verify-acc-dod\n")
        result = migrate_user_configs(config_home=home, dry_run=False)
        assert isinstance(result, SuccessResult)
        return home

    def test_shipped_table_migrates_a_temp_config_home(self, migrated_home: Path) -> None:
        assert _texts(home=migrated_home) == {
            "friction.yaml": "defaults:\n  commit: dev10x-coding:git-commit\n",
            "dod-acceptance-criteria.yaml": "- skill: dev10x-coding:verify-acc-dod\n",
            "playbooks/work-on.yaml": (
                "steps:\n  - skill: dev10x-coding:gh-pr-create\n  - skill: dev10x:playbook\n"
            ),
        }


RETIRED_IN_GH_1865 = (
    "dev10x:aws-vault",
    "dev10x:db",
    "dev10x:db-psql",
    "dev10x:k8s",
    "dev10x:playwright",
    "dev10x:qa-publish",
    "dev10x:qa-self",
    "dev10x:review-pack",
    "dev10x:sql-handoff",
    "dev10x:tts",
    "dev10x:yt-upload",
)


class TestRegister:
    @pytest.mark.parametrize("old", RETIRED_IN_GH_1865)
    def test_retired_extraction_name_is_no_longer_rewritten(self, old: str) -> None:
        assert resolve_skill_alias(name=old) == old

    @pytest.fixture
    def register_limit(self) -> str:
        removed_in = {entry.name: entry.removed_in for entry in REGISTER}
        no_entry_means_every_row_is_overdue = "0.0.0"
        return removed_in.get("SKILL_NAME_ALIASES", no_entry_means_every_row_is_overdue)

    def test_no_shipped_alias_outlives_its_register_entry(self, register_limit: str) -> None:
        assert aliases_outliving(aliases=SKILL_NAME_ALIASES, removed_in=register_limit) == []

    def test_flags_an_alias_that_outlives_the_entry(self) -> None:
        late = SkillNameAlias(old="dev10x:tts", new="dev10x-qa:tts", removed_in="0.120.0")

        assert aliases_outliving(aliases=(GOG_ALIAS, late), removed_in="0.114.0") == ["dev10x:tts"]
