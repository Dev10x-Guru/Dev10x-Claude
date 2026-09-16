"""CLI ↔ permission-catalog drift check (GH-595).

The ``dev10x-cli`` catalog group in ``baseline-permissions.yaml``
enumerates one allow-rule per agent-facing ``uvx dev10x`` subcommand so
the sanctioned CLI never prompts. New subcommands silently drift out of
the catalog and re-introduce friction (GH-269/GH-595, evidence #25/#26:
``uvx dev10x skill notify`` prompted because it was missing).

This module enumerates the live Click command tree and reports
agent-facing leaf commands that lack a covering allow-rule, so CI can
fail on drift before it reaches a session. It never introduces a broad
``Bash(uvx dev10x:*)`` rule — coverage is per-subcommand or per-group.
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from dev10x.domain.common.allow_rule import AllowRule

# Command groups that are NOT agent-facing: harness hook entry points and
# the direct validator-testing surface. They are intentionally absent
# from the agent allow-list and excluded from the drift check.
INTERNAL_GROUPS = frozenset({"hook", "validate"})

_UVX_PREFIX = "uvx dev10x "


def enumerate_leaf_commands(group, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Return the token path of every leaf command under a Click group.

    Walks via ``list_commands``/``get_command`` — Click's own group
    protocol — rather than the raw ``.commands`` dict. A ``LazyGroup``
    (``dev10x.cli``) never populates ``.commands`` for its deferred
    subcommands; they resolve only through that protocol, on demand,
    which is the whole point of the lazy-import startup optimisation
    (GH-1370). Reading ``.commands`` directly silently walked zero
    top-level groups against the live CLI, so ``find_uncovered_commands``
    always returned ``[]`` — the guard passed green while measuring
    nothing. This forces each lazy subcommand's module import at
    enumeration time (test/CI time), never at CLI-module import time, so
    the ~40ms startup budget in ``.claude/rules/performance.md`` is
    unaffected.
    """
    leaves: list[tuple[str, ...]] = []
    ctx = click.Context(group)
    for name in sorted(group.list_commands(ctx)):
        command = group.get_command(ctx, name)
        if command is None:
            continue
        path = (*prefix, name)
        if hasattr(command, "list_commands"):
            leaves.extend(enumerate_leaf_commands(command, path))
        else:
            leaves.append(path)
    return leaves


def catalog_rule_paths(catalog_path: Path) -> list[tuple[str, ...]]:
    """Return the ``uvx dev10x`` token paths covered by the dev10x-cli group."""
    data = yaml.safe_load(Path(catalog_path).read_text())
    rules = data.get("groups", {}).get("dev10x-cli", {}).get("rules", [])
    paths: list[tuple[str, ...]] = []
    for rule in rules:
        parsed = AllowRule.parse(rule)
        if parsed.tool != "Bash" or not parsed.inner.endswith(":*"):
            continue
        body = parsed.inner[: -len(":*")].rstrip()
        if not body.startswith(_UVX_PREFIX):
            continue
        path = body[len(_UVX_PREFIX) :]
        if not path or any(char in path for char in ":()"):
            continue
        paths.append(tuple(path.split()))
    return paths


def _is_covered(command: tuple[str, ...], rule_paths: list[tuple[str, ...]]) -> bool:
    """A command is covered when some rule path is a token-prefix of it."""
    return any(command[: len(rule)] == rule for rule in rule_paths)


def find_uncovered_commands(*, cli_group, catalog_path: Path) -> list[str]:
    """Return agent-facing CLI leaf commands lacking a catalog allow-rule."""
    rule_paths = catalog_rule_paths(catalog_path)
    uncovered: list[str] = []
    for command in enumerate_leaf_commands(cli_group):
        if command[0] in INTERNAL_GROUPS:
            continue
        if not _is_covered(command, rule_paths):
            uncovered.append("uvx dev10x " + " ".join(command))
    return uncovered
