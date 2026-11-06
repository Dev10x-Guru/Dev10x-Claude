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

import yaml

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


def _load_document(*, path: Path) -> Result[dict[str, Any]]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return err(f"cannot read {path}: {exc}")
    except yaml.YAMLError as exc:
        return err(f"cannot parse {path}: {exc}")
    if document is None:
        return ok({})
    if not isinstance(document, dict):
        return err(f"{path}: the top level must be a mapping")
    return ok(document)


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
    loaded = _load_document(path=config_path)
    if not isinstance(loaded, SuccessResult):
        return loaded
    document = loaded.value
    report = evaluate_projects(
        document,
        scheme=MatchScheme.REPO,
        source=source,
        target=repo,
    )
    index = report.matched_index
    entry = document["projects"][index] if index is not None else None
    holder = entry if isinstance(entry, dict) and BLOCKING_BOTS_KEY in entry else document
    globs: tuple[str, ...] = ()
    if BLOCKING_BOTS_KEY in holder:
        parsed = _globs(raw=holder[BLOCKING_BOTS_KEY], source=source)
        if not isinstance(parsed, SuccessResult):
            return parsed
        globs = parsed.value
    return ok(
        BlockingBotsConfig(
            source=source,
            globs=globs,
            project_status=report.status.value,
        )
    )
