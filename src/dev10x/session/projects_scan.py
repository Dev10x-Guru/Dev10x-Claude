"""Scan every Tier-2 config's `projects:` list against this checkout (GH-1375).

``dev10x config doctor`` reports file *location* and schema version. It
never evaluated the one key that decides whether a Tier-2 file applies
at all, so a ``projects:`` block whose globs select nothing sat there
looking correct — the failure ADR-0026 was written about.

Each file is scanned under the scheme ADR-0026 assigns it:
``friction.yaml`` against the checkout's directory path, and the
prose-resolved files against ``nameWithOwner``. A file that is absent,
or that carries no ``projects:`` list, produces no finding — only a
list that was evaluated and matched nothing, or that could not be
evaluated at all, is worth a reader's attention.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.common.result import SuccessResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.project_match import (
    MatchScheme,
    ProjectsReport,
    evaluate_projects,
)
from dev10x.session.preset_pin import probe_path, resolve_repo_identity
from dev10x.session.repo_address import resolve_name_with_owner

log = logging.getLogger(__name__)

NO_REPO_ROOT_REASON = "not in a git repository — the checkout path is unknown"


def _load_mapping(path: Path) -> dict[str, Any] | None:
    """Load a YAML mapping, or ``None`` when the file is absent/unreadable.

    A malformed Tier-2 file is a real condition a user can hit by hand.
    It is logged and skipped rather than raised: the scan is a doctor
    report over several files, and one bad file must not hide the rest.
    """
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        log.debug("could not read %s", path, exc_info=exc)
        return None
    return data if isinstance(data, dict) else None


def _repo_scheme_files() -> list[Path]:
    """Repo-addressed Tier-2 files, playbook overrides included."""
    files = [
        Dev10xConfigDir.settings_pr_merge_yaml(),
        Dev10xConfigDir.gitmoji_yaml(),
    ]
    playbooks = Dev10xConfigDir.playbooks_dir()
    if playbooks.is_dir():
        files.extend(sorted(p for p in playbooks.glob("*.yaml") if p.is_file()))
    return files


def scan_projects_lists(*, cwd: str | None = None) -> list[ProjectsReport]:
    """Evaluate every Tier-2 ``projects:`` list against this checkout."""
    identity = resolve_repo_identity(cwd=cwd)
    if isinstance(identity, SuccessResult):
        path_target: str | None = probe_path(identity.value)
        path_reason = None
    else:
        path_target, path_reason = None, NO_REPO_ROOT_REASON

    address = resolve_name_with_owner(cwd=cwd)
    if isinstance(address, SuccessResult):
        repo_target: str | None = address.value
        repo_reason = None
    else:
        repo_target, repo_reason = None, address.error

    reports: list[ProjectsReport] = []
    friction = Dev10xConfigDir.friction_yaml()
    document = _load_mapping(friction)
    if document is not None:
        reports.append(
            evaluate_projects(
                document,
                scheme=MatchScheme.PATH,
                source=str(friction),
                target=path_target,
                unresolved_reason=path_reason,
            )
        )
    for path in _repo_scheme_files():
        document = _load_mapping(path)
        if document is None:
            continue
        reports.append(
            evaluate_projects(
                document,
                scheme=MatchScheme.REPO,
                source=str(path),
                target=repo_target,
                unresolved_reason=repo_reason,
            )
        )
    return reports
