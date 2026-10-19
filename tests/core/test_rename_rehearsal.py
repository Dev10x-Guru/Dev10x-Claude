"""Stage A exit rehearsal: rename one skill and back (ADR-0034, GH-1560).

Runs NS-35 (``dev10x skill rename``) and NS-36 (the user-config
migration) end to end against a copy of the repository's skill tree in
``tmp_path``. ``gog`` is the subject: 8 references, all inside the
communication area it will leave with in B4. The live checkout is never
written; the rehearsal proves the round trip leaves the copy
byte-identical and the NS-05b reference inventory unchanged.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from dev10x.core.domain.common.result import SuccessResult
from dev10x.core.domain.deprecations import REGISTER
from dev10x.core.plugin_map import load_plugin_map
from dev10x.core.skill_references import (
    SCANNED_DIRS,
    SCANNED_FILES,
    SCANNED_FRAGMENT_DIRS,
    count_references,
    scanned_paths,
)
from dev10x.core.skill_rename import RenamePlan, count_mentions, plan_rename_from_text
from dev10x.core.skills.upgrade_cleanup.skill_names import (
    SkillNameAlias,
    migrate_user_configs,
    resolve_skill_alias,
)
from dev10x.subprocess_utils import get_plugin_root

INVENTORY_PATH = Path(__file__).parents[1] / "fixtures" / "skill_reference_inventory.json"
OLD = "dev10x:gog"
NEW = "dev10x-comm:gog"
USER_FRICTION = "defaults:\n  notify_skill: dev10x:gog\n"


@dataclass(frozen=True)
class Rehearsal:
    before: dict[str, bytes]
    after_round_trip: dict[str, bytes]
    forward: RenamePlan
    inventory_moved: dict[str, int]
    inventory_restored: dict[str, int]
    new_name_mentions: int
    migrated_friction: str
    second_migration: list[object]
    resolved: str


def _snapshot(*, root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _copy_repository(*, source: Path, target: Path) -> None:
    for directory in SCANNED_DIRS:
        shutil.copytree(source / directory, target / directory, symlinks=True)
    for relative in SCANNED_FILES:
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target / relative)
    for directory in SCANNED_FRAGMENT_DIRS:
        (target / directory).mkdir(parents=True, exist_ok=True)
        for fragment in (source / directory).glob("*.yaml"):
            shutil.copy2(fragment, target / directory / fragment.name)


def _plan(*, root: Path, old: str, new: str) -> RenamePlan:
    result = plan_rename_from_text(root=root, old=old, new=new, plugin_map=load_plugin_map())
    assert isinstance(result, SuccessResult), result
    return result.value


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory: pytest.TempPathFactory) -> Rehearsal:
    root = tmp_path_factory.mktemp("rehearsal-repo")
    _copy_repository(source=get_plugin_root(), target=root)
    before = _snapshot(root=root)

    forward = _plan(root=root, old=OLD, new=NEW)
    forward.apply()
    inventory_moved = count_references(paths=scanned_paths(root=root))
    new_name_mentions = count_mentions(paths=scanned_paths(root=root), name=forward.new)

    config_home = tmp_path_factory.mktemp("rehearsal-config-home")
    (config_home / "friction.yaml").write_text(USER_FRICTION)
    removed_in = {entry.name: entry for entry in REGISTER}["SKILL_NAME_ALIASES"].removed_in
    aliases = (SkillNameAlias(old=OLD, new=NEW, removed_in=removed_in),)
    migrate_user_configs(config_home=config_home, aliases=aliases, dry_run=False)
    second = migrate_user_configs(config_home=config_home, aliases=aliases, dry_run=False)
    assert isinstance(second, SuccessResult)

    _plan(root=root, old=NEW, new=OLD).apply()

    return Rehearsal(
        before=before,
        after_round_trip=_snapshot(root=root),
        forward=forward,
        inventory_moved=inventory_moved,
        inventory_restored=count_references(paths=scanned_paths(root=root)),
        new_name_mentions=new_name_mentions,
        migrated_friction=(config_home / "friction.yaml").read_text(),
        second_migration=list(second.value),
        resolved=resolve_skill_alias(name=OLD, aliases=aliases),
    )


@pytest.fixture(scope="module")
def baseline() -> dict[str, int]:
    return json.loads(INVENTORY_PATH.read_text())


class TestForwardRename:
    def test_moves_every_pinned_reference(
        self,
        rehearsal: Rehearsal,
        baseline: dict[str, int],
    ) -> None:
        assert rehearsal.forward.replacements == baseline["gog"]

    def test_new_name_carries_the_whole_count(
        self,
        rehearsal: Rehearsal,
        baseline: dict[str, int],
    ) -> None:
        assert rehearsal.new_name_mentions == baseline["gog"]

    def test_inventory_drops_only_the_moved_skill(
        self,
        rehearsal: Rehearsal,
        baseline: dict[str, int],
    ) -> None:
        expected = dict(baseline)
        del expected["gog"]

        assert rehearsal.inventory_moved == expected


class TestUserConfigMigration:
    def test_rewrites_the_old_name(self, rehearsal: Rehearsal) -> None:
        assert rehearsal.migrated_friction == "defaults:\n  notify_skill: dev10x-comm:gog\n"

    def test_is_idempotent(self, rehearsal: Rehearsal) -> None:
        assert rehearsal.second_migration == []

    def test_old_name_resolves_through_the_alias(self, rehearsal: Rehearsal) -> None:
        assert rehearsal.resolved == NEW


class TestRoundTrip:
    def test_tree_is_byte_identical(self, rehearsal: Rehearsal) -> None:
        assert rehearsal.after_round_trip == rehearsal.before

    def test_inventory_matches_the_pinned_baseline(
        self,
        rehearsal: Rehearsal,
        baseline: dict[str, int],
    ) -> None:
        assert rehearsal.inventory_restored == baseline
