"""Runtime policy-resolution caller (PAP-6, GH-868).

``resolve_effect(context=...)`` (context-scoped policy resolution) and
:func:`~dev10x.domain.common.policy_resolution.load_policy_layers` shipped
in PAP-1/PAP-5 with full tests but **no production caller** — nothing
loaded the layered catalog at runtime and nothing carried the active-skill
name into resolution, so the context-scoped gate never actually ran
(GH-819 AC item 3).

This module stands up that caller as the ``dev10x permission resolve``
command: it loads the plugin / user / project tiers via
:func:`load_policy_layers` and resolves one tool-call signature through
:func:`resolve_effect`, passing ``context=`` for the active skill. Per the
GH-819 design gate this is a **CLI subcommand**, not a live PreToolUse
hook — an inspectable caller with no runtime blast radius. Promoting the
same resolver into a live hook is tracked separately.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.common.policy_resolution import load_policy_layers, resolve_effect

_NO_MATCH = "none (no matching policy — the harness prompts)"


def resolve_report(
    *,
    signature: str,
    context: str = "",
    plugin_path: str | Path | None = None,
    user_path: str | Path | None = None,
    project_path: str | Path | None = None,
) -> list[str]:
    """Resolve ``signature`` through the layered catalog; return report lines.

    Loads up to three tiers (plugin default, user-private, project-local)
    via :func:`load_policy_layers` — each tolerant of a missing or
    malformed file — then resolves the effect with ``context`` carrying the
    active skill. An unmatched signature reports ``none`` because the
    engine leaves the no-decision fallback to the harness prompt.
    """
    policies = load_policy_layers(
        plugin_path=plugin_path,
        user_path=user_path,
        project_path=project_path,
    )
    effect = resolve_effect(policies=policies, signature=signature, context=context)
    decision = effect.value if effect is not None else _NO_MATCH
    return [
        f"Signature: {signature}",
        f"Context:   {context or '(unscoped)'}",
        f"Layers:    {len(policies)} policies loaded",
        f"Effect:    {decision}",
    ]


__all__ = ["resolve_report"]
