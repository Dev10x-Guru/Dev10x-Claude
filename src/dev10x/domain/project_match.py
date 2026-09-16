"""Evaluate a `projects:` list and name the scheme its globs address (GH-1375).

ADR-0026 settled that ``projects[].match`` carries two incompatible
meanings across ``~/.config/Dev10x/``: a directory-path glob in
``friction.yaml`` (code-backed, ADR-0018 D3) and an ``org/repo`` glob in
every prose-resolved file. The repo-addressed side renames to
``match_repo:``; ``match:`` stays a deprecated alias there for one
release, because nothing rewrites a user's hand-edited config.

The rename only makes a crossed convention legible. What prevents the
recurrence is :class:`ProjectsReport`, which keeps four outcomes apart
that every reader previously collapsed into silence:

``ABSENT``
    The file carries no ``projects:`` list — nothing was asked.
``UNRESOLVED``
    The target could not be determined (a repo with no ``origin``
    remote, say). The list was never evaluated — "did not look", not
    "found nothing".
``NO_MATCH``
    Entries were evaluated against a known target and none selected.
``MATCHED``
    An entry selected.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

PATH_MATCH_KEY = "match"
REPO_MATCH_KEY = "match_repo"


class MatchScheme(StrEnum):
    """Which fact an entry's globs are compared against.

    ``PATH`` is ``friction.yaml`` — an absolute directory path, keyed by
    the git common dir so one entry covers every worktree. ``REPO`` is
    the prose-resolved files — the repo's ``nameWithOwner``.
    """

    PATH = "path"
    REPO = "repo"

    @property
    def key(self) -> str:
        return PATH_MATCH_KEY if self is MatchScheme.PATH else REPO_MATCH_KEY


class ProjectsStatus(StrEnum):
    """Outcome of evaluating a ``projects:`` list."""

    ABSENT = "absent"
    UNRESOLVED = "unresolved"
    NO_MATCH = "no_match"
    MATCHED = "matched"


@dataclass(frozen=True)
class EntryReport:
    """One ``projects[]`` entry, as evaluated against a target."""

    index: int
    patterns: tuple[str, ...]
    matched: bool
    deprecated_alias: bool
    shape_warnings: tuple[str, ...]


@dataclass(frozen=True)
class ProjectsReport:
    """What evaluating one config file's ``projects:`` list established."""

    source: str
    scheme: MatchScheme
    status: ProjectsStatus
    target: str | None = None
    unresolved_reason: str | None = None
    entries: tuple[EntryReport, ...] = ()

    @property
    def matched_index(self) -> int | None:
        for entry in self.entries:
            if entry.matched:
                return entry.index
        return None

    @property
    def deprecated_alias_indexes(self) -> tuple[int, ...]:
        return tuple(entry.index for entry in self.entries if entry.deprecated_alias)

    @property
    def shape_warnings(self) -> tuple[tuple[int, str], ...]:
        return tuple(
            (entry.index, warning) for entry in self.entries for warning in entry.shape_warnings
        )

    @property
    def needs_attention(self) -> bool:
        """True when a reader should be told something about this file.

        ``UNRESOLVED`` counts even with no entries: a list that was never
        evaluated is exactly the state this report exists to surface.
        """
        return (
            self.status in (ProjectsStatus.NO_MATCH, ProjectsStatus.UNRESOLVED)
            or bool(self.deprecated_alias_indexes)
            or bool(self.shape_warnings)
        )


def read_patterns(entry: Any, *, scheme: MatchScheme) -> tuple[tuple[str, ...], bool]:
    """Return an entry's globs and whether they came from a deprecated alias.

    A repo-addressed entry prefers ``match_repo:`` and falls back to
    ``match:``. A path-addressed entry has only ``match:``, so it can
    never report an alias. A scalar glob is accepted as a one-element
    list — ``pin_project_prefs`` writes a list, but a hand-edited file
    commonly carries a bare string.
    """
    if not isinstance(entry, dict):
        return (), False
    if scheme is MatchScheme.REPO and REPO_MATCH_KEY in entry:
        return _as_patterns(entry[REPO_MATCH_KEY]), False
    raw = entry.get(PATH_MATCH_KEY)
    if raw is None:
        return (), False
    return _as_patterns(raw), scheme is MatchScheme.REPO


def _as_patterns(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if isinstance(item, str))
    return ()


def glob_shape_warnings(pattern: str, *, scheme: MatchScheme) -> tuple[str, ...]:
    """Flag a glob whose shape belongs to the other addressing scheme.

    Only the unambiguous halves of ADR-0026's rule are enforced. Under
    ``match:``, a pattern containing ``/`` that starts with neither
    ``*/`` nor ``/`` is an ``org/repo`` glob — ``Dev10x-Guru/*`` can
    never hit an absolute path. An absolute glob (``/work/dx/**``) is
    legitimate here, so the leading ``/`` is not enough on its own.

    Under ``match_repo:``, a leading ``/`` or a ``**`` segment is a path
    glob: ``nameWithOwner`` has exactly one ``/`` and no leading slash.
    A leading ``*/`` is deliberately NOT flagged — ADR-0026 documents
    ``*/<repo>`` as the portable form that resolves under both schemes,
    and the ADR's own "suspicious under ``match_repo:``" note qualifies
    itself with "only if the user meant a path", which is not knowable
    from the pattern.
    """
    if scheme is MatchScheme.PATH:
        if "/" in pattern and not pattern.startswith(("*/", "/")):
            return (
                f"{pattern!r} looks like an org/repo glob under `match:`, which is compared "
                "against an absolute directory path. Use `*/<repo>` or an absolute path glob.",
            )
        return ()
    if pattern.startswith("/") or "**" in pattern:
        return (
            f"{pattern!r} looks like a directory-path glob under `match_repo:`, which is "
            "compared against `org/repo`. Use `org/*` or `*/<repo>`.",
        )
    return ()


def matches(pattern: str, *, target: str, scheme: MatchScheme) -> bool:
    """Test one glob against ``target`` under ``scheme``.

    Path matching mirrors ``_match_globs`` in
    :mod:`dev10x.domain.documents.session_yaml`: each pattern is tried
    against the full path and against the final segment, so ``*/<repo>``
    and a bare repo name both work. Repo matching is a plain ``fnmatch``
    against ``nameWithOwner``.
    """
    if scheme is MatchScheme.REPO:
        return fnmatch.fnmatch(target, pattern)
    base = target.rstrip("/").rsplit("/", 1)[-1]
    return fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(base, pattern)


def evaluate_projects(
    document: Any,
    *,
    scheme: MatchScheme,
    source: str,
    target: str | None,
    unresolved_reason: str | None = None,
) -> ProjectsReport:
    """Evaluate a loaded config document's ``projects:`` list.

    ``target`` of ``None`` yields ``UNRESOLVED`` whenever a list is
    present: the entries are still reported (so a shape warning is not
    lost) but ``matched`` is ``False`` for all of them and the status
    says the comparison never happened.
    """
    projects = document.get("projects") if isinstance(document, dict) else None
    if not isinstance(projects, list) or not projects:
        return ProjectsReport(
            source=source,
            scheme=scheme,
            status=ProjectsStatus.ABSENT,
            target=target,
            unresolved_reason=unresolved_reason,
        )

    entries: list[EntryReport] = []
    any_matched = False
    for index, entry in enumerate(projects):
        patterns, deprecated = read_patterns(entry, scheme=scheme)
        warnings = tuple(
            warning
            for pattern in patterns
            for warning in glob_shape_warnings(pattern, scheme=scheme)
        )
        matched = (
            not any_matched
            and target is not None
            and any(matches(p, target=target, scheme=scheme) for p in patterns)
        )
        any_matched = any_matched or matched
        entries.append(
            EntryReport(
                index=index,
                patterns=patterns,
                matched=matched,
                deprecated_alias=deprecated and bool(patterns),
                shape_warnings=warnings,
            )
        )

    if target is None:
        status = ProjectsStatus.UNRESOLVED
    elif any_matched:
        status = ProjectsStatus.MATCHED
    else:
        status = ProjectsStatus.NO_MATCH
    return ProjectsReport(
        source=source,
        scheme=scheme,
        status=status,
        target=target,
        unresolved_reason=unresolved_reason,
        entries=tuple(entries),
    )


def describe(report: ProjectsReport) -> list[str]:
    """Render a report as CLI lines — empty when nothing needs saying."""
    if not report.needs_attention:
        return []
    lines = [f"  - {report.source}"]
    if report.status is ProjectsStatus.UNRESOLVED:
        reason = report.unresolved_reason or "target could not be determined"
        lines.append(
            f"      {len(report.entries)} `projects:` entr"
            f"{'y' if len(report.entries) == 1 else 'ies'} NOT evaluated — {reason}."
        )
    elif report.status is ProjectsStatus.NO_MATCH:
        lines.append(
            f"      no `{report.scheme.key}:` glob matched {report.target!r} "
            f"({len(report.entries)} entr{'y' if len(report.entries) == 1 else 'ies'} checked)."
        )
    for index in report.deprecated_alias_indexes:
        lines.append(
            f"      entry {index}: `match:` is a deprecated alias here — "
            f"rename it to `{REPO_MATCH_KEY}:` (ADR-0026)."
        )
    for index, warning in report.shape_warnings:
        lines.append(f"      entry {index}: {warning}")
    return lines
