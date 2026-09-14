"""Persist and report the project's IDE choice (GH-1261).

The write half of IDE-keyed seeding, mirroring
:mod:`dev10x.session.tracker_pin`: the onboarding IDE gate calls
:func:`pin_ide` once, and every later ``ensure-base`` run reads the
answer back through :mod:`dev10x.skills.permission.ide_resolve`.

Keyed by the repo stem from the git **common dir**, through the shared
:func:`~dev10x.session.preset_pin.pin_project_prefs` writer — an IDE is
a property of the checkout, not of one worktree of it.
"""

from __future__ import annotations

from typing import Any

from dev10x.domain.common.ide_choice import Ide, parse_ide
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.documents.session_yaml import FrictionYamlDocument
from dev10x.session.preset_pin import (
    pin_project_prefs,
    probe_path,
    resolve_repo_identity,
)

IDE_VALUES: tuple[str, ...] = tuple(ide.value for ide in Ide)


def pin_ide(
    *,
    ide: str,
    scope: str = "repo",
    cwd: str | None = None,
) -> Result[dict[str, Any]]:
    """Persist the project's IDE into the global ``friction.yaml``.

    Idempotent — an entry already covering this checkout is replaced,
    never duplicated. An unrecognised name fails loud here rather than
    degrading to ``none`` at the next seeding run, when the connection
    to the typo would be long lost and the symptom is only an IDE whose
    tools never stopped prompting.
    """
    parsed = parse_ide(ide)
    if parsed is None:
        return err(f"unknown ide {ide!r}; expected one of {list(IDE_VALUES)}")
    return pin_project_prefs(prefs={"ide": parsed.value}, scope=scope, cwd=cwd)


def ide_status(*, cwd: str | None = None) -> Result[dict[str, Any]]:
    """Report whether this repo has a durable IDE choice yet.

    ``pinned: false`` is the condition that warrants asking. Unlike
    ``tracker_status``, a resolved ``none`` is a real answer and not a
    stand-in for one: most checkouts genuinely run no IDE server, so an
    unpinned repo folds no rules rather than guessing an IDE.
    """
    identity_result = resolve_repo_identity(cwd=cwd)
    if isinstance(identity_result, ErrorResult):
        return err(identity_result.error)
    identity = identity_result.value

    document = FrictionYamlDocument(toplevel=probe_path(identity))
    matched = document.matched() or {}
    pinned = parse_ide(matched.get("ide"))
    fallback = parse_ide(document.defaults().get("ide"))
    resolved = pinned or fallback or Ide.default()
    return ok(
        {
            "pinned": pinned is not None,
            "ide": resolved.value,
            "source": "project" if pinned else ("defaults" if fallback else "default"),
            "repo_name": identity["name"],
            "repo_root": identity["root"],
            "choices": list(IDE_VALUES),
        }
    )


__all__ = ["IDE_VALUES", "ide_status", "pin_ide"]
