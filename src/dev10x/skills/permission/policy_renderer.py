"""Policy set → settings.json permissions renderer (PAP-3, GH-800).

Projects a :class:`Policy` set into the ``permissions`` mapping shape
Claude Code settings files carry (``allow`` / ``deny`` / ``ask`` lists
plus ``additionalDirectories``). Replaces the flat-list rendering the
maintenance flows used before the PAP refactor:

- **Effect-faithful** — each effective policy lands in the list its
  :class:`PolicyEffect` names. The shipped catalog is allow/deny today;
  ``ask`` renders as soon as ask-tier policies exist (an intended diff,
  never an accidental one).
- **Twin-variant paths (GH-47)** — rule matching in the permission
  engine is literal, so a ``~/`` rule silently fails for sessions that
  spell paths as ``/home/<user>/``. The renderer emits the resolved
  twin for every ``~/`` rule unless the catalog already carries it.
- **Workspace-scoped** — a :class:`Workspace` contributes its
  ``additionalDirectories`` so path tools operate without per-call
  prompts (GH-40).

Byte-parity with the pre-PAP output is asserted by tests with
``twin_paths=False``; the twin expansion is the one documented diff.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.common.policy import Policy, PolicyEffect
from dev10x.domain.common.workspace import Workspace


def render_permissions(
    *,
    policies: list[Policy],
    workspace: Workspace | None = None,
    home: str | None = None,
    twin_paths: bool = True,
) -> dict[str, list[str]]:
    """Render the ``permissions`` mapping for a settings file."""
    effective = [policy for policy in policies if policy.is_effective]
    rendered: dict[str, list[str]] = {}
    for key, effect in (
        ("allow", PolicyEffect.ALLOW),
        ("deny", PolicyEffect.DENY),
        ("ask", PolicyEffect.ASK),
    ):
        rules = _unique(
            rules=[policy.signature for policy in effective if policy.effect is effect]
        )
        if twin_paths:
            rules = expand_twin_paths(rules=rules, home=home)
        if rules or key in ("allow", "deny"):
            rendered[key] = rules
    if workspace is not None and workspace.additional_directories:
        rendered["additionalDirectories"] = list(workspace.additional_directories)
    return rendered


def expand_twin_paths(*, rules: list[str], home: str | None = None) -> list[str]:
    """Append the ``/home/<user>/`` twin after each ``~/`` rule (GH-47).

    A twin is only added when the catalog does not already carry it, so
    catalogs that enumerate both spellings render unchanged.
    """
    resolved_home = (home or str(Path.home())).rstrip("/")
    expanded: list[str] = []
    for rule in rules:
        expanded.append(rule)
        if "~/" not in rule:
            continue
        twin = rule.replace("~/", f"{resolved_home}/")
        if twin not in rules and twin not in expanded:
            expanded.append(twin)
    return expanded


def _unique(*, rules: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for rule in rules:
        if rule in seen:
            continue
        seen.add(rule)
        unique.append(rule)
    return unique


__all__ = ["expand_twin_paths", "render_permissions"]
