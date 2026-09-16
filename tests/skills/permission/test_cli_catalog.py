"""CLI ↔ permission-catalog drift check (GH-595).

The live-catalog test is the CI drift gate: it enumerates the real
``dev10x`` Click tree and fails when an agent-facing subcommand lacks a
covering ``dev10x-cli`` allow-rule. Running under the standard pytest CI
job means a new subcommand cannot merge without its catalog entry.

GH-1370: that gate was measuring nothing. ``dev10x.cli.cli`` is a
``LazyGroup`` (``.claude/rules/performance.md`` documents why — it
defers every subcommand import until invocation, which is what keeps
``dev10x --help`` under the 200ms startup budget). A ``LazyGroup``
never populates the base ``click.Group.commands`` dict for its
deferred entries; they resolve only through ``list_commands`` /
``get_command``, on demand. ``enumerate_leaf_commands`` used to read
``.commands`` directly, so it walked zero top-level groups against the
live CLI and ``find_uncovered_commands`` always returned ``[]`` —
``test_no_uncovered_commands`` passed 7/7 while blind to every
subcommand behind a lazy group.

``enumerate_leaf_commands`` now walks via Click's own group protocol
(``list_commands``/``get_command``), which forces each lazy module to
import at enumeration time — test/CI time, never CLI-module import
time, so the startup budget is unaffected (verified: ``uv run dev10x
--help`` is unchanged by this change, since import still happens only
inside ``get_command``).

``TestEnumerationSeesLazyGroups`` below is the GH-1215 counter-check:
it counts the groups ``dev10x.cli`` actually declares as lazy and
asserts the enumeration can see all of them, so a future narrowing
(e.g. reverting to ``.commands``) fails loudly instead of silently
shrinking the guard's field of view again.

Turning the guard on immediately surfaced real, pre-existing gaps —
commands added since the catalog was last updated (GH-1317 catalogued
two of them: ``dev10x foreman probe|watch``). Cataloguing which of
those deserve a ``dev10x-cli`` allow-rule is a separate judgement this
PR does not make (GH-1313's precedent: land the invariant, triage the
findings separately). ``UNTRIAGED_CLI_BACKLOG`` is the ratchet that
lets the guard bite on *new* drift today without deciding the 24
pre-existing gaps as a side effect of fixing it.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import yaml

import dev10x.cli as cli_module
import dev10x.skills.permission as permission_pkg
from dev10x.cli import cli
from dev10x.skills.permission.cli_catalog import (
    catalog_rule_paths,
    enumerate_leaf_commands,
    find_uncovered_commands,
)

_LAZY_GROUP_KEY = re.compile(r'"([\w-]+)":\s*"dev10x\.')


def _declared_lazy_groups() -> set[str]:
    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    return set(_LAZY_GROUP_KEY.findall(source))


CATALOG = Path(permission_pkg.__file__).parent / "baseline-permissions.yaml"

#: Commands the now-working enumeration found uncovered the moment it
#: started measuring real output (GH-1370). This is a ratchet over
#: pre-existing drift, not an exemption: each entry still needs a
#: decision — add a ``dev10x-cli`` allow-rule in
#: ``baseline-permissions.yaml``, or leave it deliberately uncovered —
#: and that triage is tracked as a follow-up, not made here. The set
#: may shrink freely and must never grow: ``test_backlog_only_shrinks``
#: pins it to its starting size, and ``test_backlog_carries_no_resolved_entries``
#: catches an entry that has already been catalogued or has vanished
#: from the live CLI.
UNTRIAGED_CLI_BACKLOG_STARTING_SIZE = 24

UNTRIAGED_CLI_BACKLOG: frozenset[str] = frozenset(
    {
        "uvx dev10x deps sweep",
        "uvx dev10x foreman probe",
        "uvx dev10x foreman watch",
        "uvx dev10x github learn",
        "uvx dev10x github review-rules",
        "uvx dev10x orchestration stranded-work",
        "uvx dev10x permission audit",
        "uvx dev10x permission catalog-diff",
        "uvx dev10x permission catalog-gap",
        "uvx dev10x permission ensure-ignored",
        "uvx dev10x permission ensure-safety-keys",
        "uvx dev10x permission promote-plan",
        "uvx dev10x permission provenance",
        "uvx dev10x permission resolve",
        "uvx dev10x permission seed-worktree",
        "uvx dev10x session pin",
        "uvx dev10x session reap",
        "uvx dev10x session set-friction",
        "uvx dev10x session set-playbook",
        "uvx dev10x spec drift",
        "uvx dev10x usage blocks",
        "uvx dev10x watchdog probe",
        "uvx dev10x watchdog sessions",
        "uvx dev10x watchdog wake",
    }
)


def _write_catalog(path: Path, rules: list[str]) -> Path:
    path.write_text(yaml.safe_dump({"groups": {"dev10x-cli": {"rules": rules}}}))
    return path


def _build_cli() -> click.Group:
    @click.group()
    def root() -> None: ...

    @root.group()
    def permission() -> None: ...

    @permission.command()
    def clean() -> None: ...

    @permission.command(name="brand-new")
    def brand_new() -> None: ...  # synthetic uncovered subcommand

    @root.group()
    def hook() -> None: ...

    @hook.command(name="validate-bash")
    def validate_bash() -> None: ...  # internal — excluded

    return root


class TestEnumerateLeafCommands:
    def test_recurses_to_leaves(self) -> None:
        leaves = enumerate_leaf_commands(_build_cli())
        assert ("permission", "clean") in leaves
        assert ("permission", "brand-new") in leaves
        assert ("hook", "validate-bash") in leaves


class TestCatalogRulePaths:
    def test_parses_uvx_dev10x_rules(self, tmp_path: Path) -> None:
        catalog = _write_catalog(
            tmp_path / "c.yaml",
            [
                "Bash(uvx dev10x permission clean:*)",
                "Bash(uvx dev10x config:*)",
                "Bash(git log:*)",  # non-dev10x rule ignored
            ],
        )
        assert catalog_rule_paths(catalog) == [("permission", "clean"), ("config",)]


class TestFindUncoveredCommands:
    def test_flags_uncovered_subcommand(self, tmp_path: Path) -> None:
        catalog = _write_catalog(tmp_path / "c.yaml", ["Bash(uvx dev10x permission clean:*)"])
        uncovered = find_uncovered_commands(cli_group=_build_cli(), catalog_path=catalog)
        assert uncovered == ["uvx dev10x permission brand-new"]

    def test_group_prefix_covers_leaves(self, tmp_path: Path) -> None:
        catalog = _write_catalog(
            tmp_path / "c.yaml",
            ["Bash(uvx dev10x permission:*)"],  # group wildcard covers all leaves
        )
        uncovered = find_uncovered_commands(cli_group=_build_cli(), catalog_path=catalog)
        assert uncovered == []

    def test_internal_groups_excluded(self, tmp_path: Path) -> None:
        # `hook` is internal — never needs a catalog rule.
        catalog = _write_catalog(
            tmp_path / "c.yaml",
            [
                "Bash(uvx dev10x permission clean:*)",
                "Bash(uvx dev10x permission brand-new:*)",
            ],
        )
        uncovered = find_uncovered_commands(cli_group=_build_cli(), catalog_path=catalog)
        assert uncovered == []


class TestLiveCatalogHasNoDrift:
    """CI gate: the shipped catalog must cover every agent-facing command."""

    def test_no_uncovered_commands(self) -> None:
        uncovered = set(find_uncovered_commands(cli_group=cli, catalog_path=CATALOG))
        new_drift = uncovered - UNTRIAGED_CLI_BACKLOG
        assert not new_drift, (
            "These dev10x subcommands lack a dev10x-cli allow-rule in "
            "baseline-permissions.yaml and are not in the pre-existing "
            f"UNTRIAGED_CLI_BACKLOG — add a catalog entry: {sorted(new_drift)}"
        )

    def test_skill_notify_is_covered(self) -> None:
        # GH-595 regression: the missing subcommand that prompted in-session.
        assert "uvx dev10x skill notify" not in find_uncovered_commands(
            cli_group=cli, catalog_path=CATALOG
        )

    def test_backlog_only_shrinks(self) -> None:
        assert len(UNTRIAGED_CLI_BACKLOG) <= UNTRIAGED_CLI_BACKLOG_STARTING_SIZE, (
            f"UNTRIAGED_CLI_BACKLOG has grown to {len(UNTRIAGED_CLI_BACKLOG)} from its "
            f"{UNTRIAGED_CLI_BACKLOG_STARTING_SIZE}-command starting point. It is a "
            "ratchet over drift that predates the guard, not a place to park new "
            "drift — add the missing dev10x-cli allow-rule in "
            "baseline-permissions.yaml instead."
        )

    def test_backlog_carries_no_resolved_entries(self) -> None:
        uncovered = set(find_uncovered_commands(cli_group=cli, catalog_path=CATALOG))
        resolved = UNTRIAGED_CLI_BACKLOG - uncovered
        assert not resolved, (
            "these commands no longer need triage — they are catalogued or gone "
            "from the live CLI. Drop them from UNTRIAGED_CLI_BACKLOG so the "
            f"remaining debt is countable: {sorted(resolved)}"
        )


class TestEnumerationSeesLazyGroups:
    """GH-1215 counter-check: a narrowed walk must fail loudly, not silently.

    GH-1370 found the enumeration blind to every ``LazyGroup`` subcommand.
    This pins the fix by counting the groups ``dev10x.cli`` actually
    declares as lazy and asserting the walker can see every one of them —
    so reverting to ``.commands`` (or any other narrowing) fails here
    instead of shrinking ``find_uncovered_commands``'s field of view back
    to zero.
    """

    def test_top_level_lazy_groups_are_discovered(self) -> None:
        declared = _declared_lazy_groups()
        assert declared, f"no lazy_subcommands entries found in {cli_module.__file__}"

        ctx = click.Context(cli)
        discovered = set(cli.list_commands(ctx))
        missing = declared - discovered
        assert not missing, (
            f"dev10x.cli declares {sorted(declared)} as lazy subcommands but "
            f"cli.list_commands() only sees {sorted(discovered)}. The enumeration "
            f"walk is blind to: {sorted(missing)} (GH-1215)."
        )

    def test_populated_lazy_groups_yield_leaves(self) -> None:
        # `validate` is a deliberately empty group (direct validator access
        # for testing, no subcommands registered) — excluded rather than
        # asserted to have leaves it was never meant to have.
        known_empty = {"validate"}
        declared = _declared_lazy_groups() - known_empty

        leaves = enumerate_leaf_commands(cli)
        discovered_tops = {command[0] for command in leaves}
        missing = declared - discovered_tops
        assert not missing, (
            f"enumerate_leaf_commands(cli) found no leaf commands under: "
            f"{sorted(missing)}. Either the group has no subcommands (add it to "
            "`known_empty` with a reason) or enumeration is silently skipping it."
        )
