"""Flat base_permissions catalog → structured Policy entries (PAP-2, GH-799).

Bridges the two catalogs that drifted apart (GH-796): the flat
``base_permissions``/``base_denies`` lists in ``projects.yaml`` (what
``ensure_base`` actually ships to settings files) and the grouped,
tier-tagged ``baseline-permissions.yaml``. Every flat rule becomes a
:class:`Policy` — enriched with tier/group/sensitivity from the grouped
catalog when the same rule exists there, then classified by two
bootstrap passes:

- **claude.ai MCP pass** — connector rules are grouped per server and
  read-verb tools are tagged ``benign`` so proactive seeding can
  distinguish reads from writes.
- **fence-tools subpass** — the ``<runner> --version`` probe rules are
  grouped and marked trivially reversible; they are the narrow allows
  carved out of the fence-tool ``ask`` surface (GH-310).

Moved into the domain layer from
``dev10x.skills.permission.policy_catalog_migration`` (GH-819 domain
purity follow-up, ADR-0008): :func:`~dev10x.domain.common.policy_resolution.load_policy_layers`
calls :func:`migrate_flat_config` directly, and a ``domain/`` module
must not import from ``skills/`` (the adapter layer). The skills module
re-exports this function for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.policy import (
    Policy,
    PolicyCatalog,
    PolicyEffect,
    PolicySensitivity,
    PolicySource,
)

# src/dev10x/domain/common/policy_migration.py -> src/dev10x/skills/permission/
BASELINE_CATALOG_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "permission" / "baseline-permissions.yaml"
)

CLAUDE_AI_MCP_GROUP = "claude-ai-mcp"
FENCE_TOOL_PROBE_GROUP = "fence-tool-probes"
DEFAULT_TIER = 2

_CONNECTOR_PREFIXES = ("mcp__claude_ai_", "mcp__linear-server__")
_MCP_READ_VERBS = ("get_", "list_", "search_", "read_", "extract_", "find_")
_FENCE_TOOL_RUNNERS = frozenset({"npx", "npm", "pnpm", "pipx", "bun", "bunx", "yarn", "uvx", "uv"})


def load_baseline_policies() -> list[Policy]:
    """Load the grouped plugin catalog for enrichment lookups."""
    return PolicyCatalog.load(BASELINE_CATALOG_PATH)


def migrate_flat_config(
    *,
    config: dict,
    baseline_policies: list[Policy] | None = None,
) -> list[Policy]:
    """Convert ``base_permissions``/``base_denies`` into Policy entries.

    Order is preserved per effect so the compatibility shim can
    reproduce the original flat lists exactly. Non-string entries are
    skipped, mirroring :meth:`PolicyCatalog.from_baseline_dict`.
    """
    if baseline_policies is None:
        baseline_policies = load_baseline_policies()
    baseline_by_signature = {policy.signature: policy for policy in baseline_policies}

    policies: list[Policy] = []
    for rule, effect in _flat_rules(config=config):
        policies.append(
            _migrate_rule(
                rule=rule,
                effect=effect,
                baseline=baseline_by_signature.get(rule),
            )
        )
    return policies


def _flat_rules(*, config: dict) -> list[tuple[str, PolicyEffect]]:
    pairs: list[tuple[str, PolicyEffect]] = []
    for key, effect in (
        ("base_permissions", PolicyEffect.ALLOW),
        ("base_denies", PolicyEffect.DENY),
    ):
        entries = config.get(key)
        if not isinstance(entries, list):
            continue
        pairs.extend((rule, effect) for rule in entries if isinstance(rule, str))
    return pairs


def _migrate_rule(*, rule: str, effect: PolicyEffect, baseline: Policy | None) -> Policy:
    tier = baseline.tier if baseline is not None else DEFAULT_TIER
    group = baseline.group if baseline is not None else ""
    sensitivity = baseline.sensitivity if baseline is not None else PolicySensitivity.UNSPECIFIED
    reversible: bool | None = None

    if not group and _is_connector_rule(rule=rule):
        group = CLAUDE_AI_MCP_GROUP
        if sensitivity is PolicySensitivity.UNSPECIFIED and _is_connector_read(rule=rule):
            sensitivity = PolicySensitivity.BENIGN
    if not group and _is_fence_tool_probe(rule=rule):
        group = FENCE_TOOL_PROBE_GROUP
        reversible = True

    return Policy.from_rule_str(
        rule,
        tier=tier,
        source=PolicySource.PLUGIN_DEFAULT,
        effect=effect,
        sensitivity=sensitivity,
        group=group,
        id=rule,
        reversible=reversible,
    )


def _is_connector_rule(*, rule: str) -> bool:
    return rule.startswith(_CONNECTOR_PREFIXES)


def _is_connector_read(*, rule: str) -> bool:
    tool_name = rule.rsplit("__", 1)[-1]
    return tool_name.startswith(_MCP_READ_VERBS)


def _is_fence_tool_probe(*, rule: str) -> bool:
    parsed = AllowRule.parse(rule)
    if parsed.tool != "Bash" or not parsed.inner.endswith(" --version"):
        return False
    runner = parsed.inner[: -len(" --version")]
    return runner in _FENCE_TOOL_RUNNERS


__all__ = [
    "BASELINE_CATALOG_PATH",
    "CLAUDE_AI_MCP_GROUP",
    "DEFAULT_TIER",
    "FENCE_TOOL_PROBE_GROUP",
    "load_baseline_policies",
    "migrate_flat_config",
]
