"""Which review bots a repo treats as blocking (GH-1832).

`<Dev10x config>/settings-pr-merge.yaml` already carries the per-repo
merge policy, so the blocking-bot list lives there too: a top-level
``blocking_bots:`` default and a repo-addressed ``projects:`` list
(ADR-0026 ``match_repo:``) whose first matching entry overrides it.

Each entry is a login glob matched case-insensitively against the bot's
login with any ``[bot]`` suffix removed, so ``claude`` and
``claude[bot]`` name the same account.

An absent file or key means no bot is blocking. That is an answer, not
an error: a repo with no review bots must still be able to merge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.common.config_io import ConfigIOError, load_yaml
from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.project_match import MatchScheme, ProjectsStatus, evaluate_projects

BLOCKING_BOTS_KEY = "blocking_bots"

_BOT_SUFFIX = "[bot]"


def normalize_login(login: str | None) -> str:
    """Drop the ``[bot]`` suffix REST adds and GraphQL omits."""
    name = (login or "").strip()
    if name.lower().endswith(_BOT_SUFFIX):
        name = name[: -len(_BOT_SUFFIX)]
    return name


@dataclass(frozen=True)
class BlockingBotsConfig:
    """The resolved blocking-bot globs for one repo."""

    source: str
    globs: tuple[str, ...] = ()
    project_status: str = ProjectsStatus.ABSENT.value
    found: bool = False
    stated: bool = False

    def notes(self) -> list[str]:
        """Why nothing may be blocking, when that is not an explicit choice.

        ``ready: true`` with no blocking bots reads the same whether the
        repo chose "no bot blocks" or never said, so the report says
        which (GH-1857). A ``blocking_bots:`` key — even ``[]`` — is a
        choice and gets no note. Informational: it never blocks.
        """
        if not self.found:
            return [f"{self.source} not found — no bot is blocking for this repo"]
        if self.stated:
            return []
        if self.project_status == ProjectsStatus.NO_MATCH.value:
            return [
                f"no `projects:` entry in {self.source} matched this repo and no "
                f"`{BLOCKING_BOTS_KEY}:` default is set — no bot is blocking"
            ]
        return [f"{self.source} sets no `{BLOCKING_BOTS_KEY}:` — no bot is blocking"]


def _globs(*, raw: Any, source: str) -> Result[tuple[str, ...]]:
    if raw is None:
        return err(
            f"{source}: `{BLOCKING_BOTS_KEY}:` has no value — list the login globs, "
            "write `[]` to block on no bot, or remove the key"
        )
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(g, str) and g.strip() for g in raw):
        return err(f"{source}: `{BLOCKING_BOTS_KEY}:` must be a list of login globs")
    return ok(tuple(normalize_login(g) for g in raw))


def resolve_blocking_bots(
    *,
    repo: str | None,
    path: Path | None = None,
) -> Result[BlockingBotsConfig]:
    """Resolve ``blocking_bots`` for the repo whose ``nameWithOwner`` is ``repo``.

    Returns ``err`` only when the file exists but cannot be read, parsed,
    or holds a malformed ``blocking_bots`` value — silently treating a
    typo as "nothing blocks" would let a merge through unreviewed.
    """
    config_path = path or Dev10xConfigDir.settings_pr_merge_yaml()
    source = str(config_path)
    if not config_path.is_file():
        return ok(BlockingBotsConfig(source=source))
    try:
        document = load_yaml(config_path, strict=True)
    except ConfigIOError as exc:
        return err(str(exc))
    report = evaluate_projects(
        document,
        scheme=MatchScheme.REPO,
        source=source,
        target=repo,
    )
    index = report.matched_index
    entry = document["projects"][index] if index is not None else None
    holder = entry if isinstance(entry, dict) and BLOCKING_BOTS_KEY in entry else document
    stated = BLOCKING_BOTS_KEY in holder
    globs: tuple[str, ...] = ()
    if stated:
        parsed = _globs(raw=holder[BLOCKING_BOTS_KEY], source=source)
        if not isinstance(parsed, SuccessResult):
            return parsed
        globs = parsed.value
    return ok(
        BlockingBotsConfig(
            source=source,
            globs=globs,
            project_status=report.status.value,
            found=True,
            stated=stated,
        )
    )
