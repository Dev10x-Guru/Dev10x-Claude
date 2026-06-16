"""Source-derived two-axis permission manifest (GH-600).

Every pre-approval decision needs to know two things about a surface
(an MCP tool, a CLI command, or a skill): does it **read or write**, and
how **sensitive** is the data it touches. Before this module those two
axes lived apart — read/write was a token heuristic buried in
``promote.py`` and sensitivity was a command-string classifier in
``domain/sensitivity.py`` — and the curated catalog was hand-maintained,
so it rotted (camelCase tools, new CLI subcommands, own-CLI gaps).

This module is the single source for both axes. Entries are *derived*
from live sources — the MCP tool list, the ``dev10x`` Click tree, and
skill frontmatter — never hand-typed, so the manifest cannot drift
behind what the plugin actually exposes. A CI drift-check
(:func:`find_manifest_drift`) fails when a discovered surface yields no
manifest entry, extending GH-595's ``dev10x-cli`` check to every surface.

The read/write axis reuses GH-593's camelCase-aware tokenizer via
:func:`dev10x.skills.permission.promote.classify_tokens`, so a write
tool can never be misclassified as a promotable read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from dev10x.skills.permission.cli_catalog import (
    INTERNAL_GROUPS,
    enumerate_leaf_commands,
)
from dev10x.skills.permission.promote import classify_tokens, is_sensitivity_flagged


class Surface(StrEnum):
    """The kind of thing a permission rule pre-approves."""

    MCP = "mcp"
    CLI = "cli"
    SKILL = "skill"


class Access(StrEnum):
    """Read/write axis — whether the surface mutates state."""

    READ = "read"
    WRITE = "write"
    UNKNOWN = "unknown"


class Sensitivity(StrEnum):
    """Data-sensitivity axis — what the surface touches.

    ``BENIGN`` reads are safe to seed by default; everything else is
    opt-in. ``MUTATING`` is the write counterpart (a side-effecting
    surface is sensitive by virtue of changing state); ``PII`` /
    ``INFRA`` / ``SECRET`` mark reads whose *target* is sensitive even
    when the verb is harmless.
    """

    BENIGN = "benign"
    PII = "pii"
    INFRA = "infra"
    SECRET = "secret"
    MUTATING = "mutating"


# Skill frontmatter tools that mutate the workspace directly. A skill whose
# ``allowed-tools`` lists any of these is a write surface regardless of its
# name (the name heuristic alone would miss e.g. a "polish" skill that edits).
_WRITE_SKILL_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


@dataclass(frozen=True)
class ManifestEntry:
    """One surface classified on both axes.

    ``name`` is the stable identifier used for drift matching: the
    fully-qualified MCP tool name, the ``uvx dev10x …`` command string,
    or the skill directory name.
    """

    surface: Surface
    name: str
    access: Access
    sensitivity: Sensitivity

    @property
    def key(self) -> tuple[str, str]:
        return (str(self.surface), self.name)

    @property
    def default_safe(self) -> bool:
        """True when this surface is safe to seed without an opt-in.

        A surface is default-safe only when it is a benign read — a write
        (``MUTATING``) or a sensitive-target read (``PII``/``INFRA``/
        ``SECRET``) always requires an explicit opt-in.
        """
        return self.access is Access.READ and self.sensitivity is Sensitivity.BENIGN


def _sensitivity_for(access: Access, name: str) -> Sensitivity:
    """Derive the sensitivity axis from what is knowable from the name.

    A write is ``MUTATING``; a read whose name carries a private/DM/secret
    token is ``SECRET``; everything else is ``BENIGN``. ``PII`` and
    ``INFRA`` cannot be inferred from a verb-name alone (they depend on the
    target), so they arrive only via curated overrides in
    :func:`build_manifest`.
    """
    if access is Access.WRITE:
        return Sensitivity.MUTATING
    if is_sensitivity_flagged(name):
        return Sensitivity.SECRET
    return Sensitivity.BENIGN


def _entry(surface: Surface, name: str) -> ManifestEntry:
    access = Access(classify_tokens(name))
    return ManifestEntry(surface, name, access, _sensitivity_for(access, name))


def manifest_from_mcp_tools(tool_names: Iterable[str]) -> list[ManifestEntry]:
    """Classify each fully-qualified MCP tool name on both axes."""
    return [_entry(Surface.MCP, name) for name in tool_names]


def manifest_from_cli(cli_group, *, prog: str = "uvx dev10x") -> list[ManifestEntry]:
    """Classify every agent-facing leaf command of a Click CLI tree.

    Internal command groups (hook entry points, the validator surface)
    are excluded — they are deliberately absent from the agent allow-list
    (see :data:`cli_catalog.INTERNAL_GROUPS`).
    """
    entries: list[ManifestEntry] = []
    for path in enumerate_leaf_commands(cli_group):
        if path[0] in INTERNAL_GROUPS:
            continue
        entries.append(_entry(Surface.CLI, f"{prog} " + " ".join(path)))
    return entries


def _parse_frontmatter(text: str) -> dict | None:
    """Return the YAML frontmatter block of a SKILL.md, or None if absent/invalid."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _skill_access(allowed_tools: Iterable[str]) -> Access:
    """Classify a skill as read/write from its ``allowed-tools`` list.

    A skill is a write surface when it can edit files directly
    (Write/Edit/…) or when any ``Bash(...)`` rule names a write verb
    (``git commit``, ``gh pr create``, ``push`` …). Otherwise it reads.
    """
    for tool in allowed_tools:
        head = tool.split("(", 1)[0]
        if head in _WRITE_SKILL_TOOLS:
            return Access.WRITE
        if head == "Bash":
            inner = tool[tool.find("(") + 1 : tool.rfind(")")]
            if classify_tokens(inner) == "write":
                return Access.WRITE
    return Access.READ


def manifest_from_skills(skills_dir: Path) -> list[ManifestEntry]:
    """Classify every skill under *skills_dir* from its SKILL.md frontmatter.

    A SKILL.md whose frontmatter is missing, unparseable, or carries a
    non-list ``allowed-tools`` is intentionally SKIPPED so the drift-check
    (:func:`find_manifest_drift`) reports it — a malformed skill must not
    silently fall out of the manifest. A skill with valid frontmatter and
    *no* ``allowed-tools`` is a read-only orchestration skill (no external
    surface to mutate), classified ``READ`` — not a skip.
    """
    entries: list[ManifestEntry] = []
    for skill_md in sorted(Path(skills_dir).glob("*/SKILL.md")):
        front = _parse_frontmatter(skill_md.read_text())
        if front is None:
            continue
        allowed = front.get("allowed-tools", [])
        if not isinstance(allowed, list):
            continue
        access = _skill_access(t for t in allowed if isinstance(t, str))
        name = skill_md.parent.name
        entries.append(ManifestEntry(Surface.SKILL, name, access, _sensitivity_for(access, name)))
    return entries


def build_manifest(
    *,
    mcp_tools: Iterable[str],
    cli_group,
    skills_dir: Path,
    sensitivity_overrides: Mapping[str, Sensitivity] | None = None,
) -> list[ManifestEntry]:
    """Build the full two-axis manifest from all live sources.

    ``sensitivity_overrides`` maps an entry ``name`` to a curated
    sensitivity label for cases the name heuristic cannot infer — e.g.
    Google Drive/Gmail reads are ``PII`` even though ``read``/``get`` are
    benign verbs (GH-601). Overrides apply across every surface.
    """
    overrides = sensitivity_overrides or {}
    entries = [
        *manifest_from_mcp_tools(mcp_tools),
        *manifest_from_cli(cli_group),
        *manifest_from_skills(skills_dir),
    ]
    if not overrides:
        return entries
    return [
        ManifestEntry(e.surface, e.name, e.access, overrides[e.name]) if e.name in overrides else e
        for e in entries
    ]


def discovered_surface_keys(
    *,
    mcp_tools: Iterable[str],
    cli_group,
    skills_dir: Path,
) -> set[tuple[str, str]]:
    """Enumerate every surface that the manifest is expected to cover.

    Independent of :func:`build_manifest` so the drift-check has a second
    witness: a surface a generator silently drops (e.g. a skill with
    malformed frontmatter) appears here but not in the manifest.
    """
    keys: set[tuple[str, str]] = {(str(Surface.MCP), name) for name in mcp_tools}
    for path in enumerate_leaf_commands(cli_group):
        if path[0] in INTERNAL_GROUPS:
            continue
        keys.add((str(Surface.CLI), "uvx dev10x " + " ".join(path)))
    for skill_md in Path(skills_dir).glob("*/SKILL.md"):
        keys.add((str(Surface.SKILL), skill_md.parent.name))
    return keys


def find_manifest_drift(
    *,
    mcp_tools: Iterable[str],
    cli_group,
    skills_dir: Path,
) -> list[str]:
    """Return discovered surfaces that produced no manifest entry (CI gate).

    Empty means every live MCP tool, CLI command, and skill is classified.
    A non-empty result is a drift: the manifest fell behind a surface the
    plugin actually exposes.
    """
    mcp_tools = list(mcp_tools)
    manifest = build_manifest(mcp_tools=mcp_tools, cli_group=cli_group, skills_dir=skills_dir)
    covered = {entry.key for entry in manifest}
    discovered = discovered_surface_keys(
        mcp_tools=mcp_tools, cli_group=cli_group, skills_dir=skills_dir
    )
    return sorted(f"{surface}:{name}" for surface, name in discovered - covered)
