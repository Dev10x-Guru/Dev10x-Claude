"""Tests for the Policy → settings.json renderer (PAP-3, GH-800).

The parity class is the acceptance gate: with twin expansion off, the
renderer reproduces the exact allow/deny lists the pre-PAP maintenance
flow shipped for the migrated catalog; with twins on, every diff is a
``/home/<user>/`` twin of a ``~/`` rule — the one intended change.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from dev10x.domain.common.policy import Policy, PolicyEffect, PolicyLifecycle, PolicySource
from dev10x.domain.common.workspace import Workspace
from dev10x.skills.permission.policy_renderer import expand_twin_paths, render_permissions

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROJECTS_YAML = _REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"

_HOME = "/home/tester"


def _policy(
    *,
    rule: str,
    effect: PolicyEffect = PolicyEffect.ALLOW,
    lifecycle: PolicyLifecycle = PolicyLifecycle.ACTIVE,
    enabled: bool = True,
) -> Policy:
    return Policy.from_rule_str(
        rule,
        tier=1,
        source=PolicySource.PLUGIN_DEFAULT,
        effect=effect,
        lifecycle=lifecycle,
        enabled=enabled,
    )


class TestRenderPermissions:
    def test_effects_land_in_their_lists(self) -> None:
        policies = [
            _policy(rule="Bash(ls:*)"),
            _policy(rule="Bash(sudo:*)", effect=PolicyEffect.DENY),
            _policy(rule="Bash(nc -zv:*)", effect=PolicyEffect.ASK),
        ]
        rendered = render_permissions(policies=policies, home=_HOME)
        assert rendered["allow"] == ["Bash(ls:*)"]
        assert rendered["deny"] == ["Bash(sudo:*)"]
        assert rendered["ask"] == ["Bash(nc -zv:*)"]

    def test_allow_and_deny_are_always_present(self) -> None:
        rendered = render_permissions(policies=[], home=_HOME)
        assert rendered == {"allow": [], "deny": []}

    def test_ask_is_omitted_when_no_ask_policies_exist(self) -> None:
        rendered = render_permissions(policies=[_policy(rule="Bash(ls:*)")], home=_HOME)
        assert "ask" not in rendered

    def test_disabled_and_deprecated_policies_are_not_rendered(self) -> None:
        policies = [
            _policy(rule="Bash(ls:*)", enabled=False),
            _policy(rule="Bash(cat:*)", lifecycle=PolicyLifecycle.DEPRECATED),
            _policy(rule="Bash(rg:*)"),
        ]
        rendered = render_permissions(policies=policies, home=_HOME)
        assert rendered["allow"] == ["Bash(rg:*)"]

    def test_duplicate_signatures_render_once(self) -> None:
        policies = [_policy(rule="Bash(ls:*)"), _policy(rule="Bash(ls:*)")]
        rendered = render_permissions(policies=policies, home=_HOME)
        assert rendered["allow"] == ["Bash(ls:*)"]

    def test_workspace_contributes_additional_directories(self) -> None:
        workspace = Workspace(root="/work/repo", additional_directories=("/tmp/Dev10x",))
        rendered = render_permissions(policies=[], workspace=workspace, home=_HOME)
        assert rendered["additionalDirectories"] == ["/tmp/Dev10x"]

    def test_workspace_without_directories_adds_no_key(self) -> None:
        rendered = render_permissions(
            policies=[], workspace=Workspace(root="/work/repo"), home=_HOME
        )
        assert "additionalDirectories" not in rendered


class TestTwinPathExpansion:
    def test_tilde_rule_gains_resolved_twin(self) -> None:
        rules = ["Bash(~/.claude/tools/x.py:*)"]
        assert expand_twin_paths(rules=rules, home=_HOME) == [
            "Bash(~/.claude/tools/x.py:*)",
            "Bash(/home/tester/.claude/tools/x.py:*)",
        ]

    def test_existing_twin_is_not_duplicated(self) -> None:
        rules = [
            "Bash(~/.claude/tools/x.py:*)",
            "Bash(/home/tester/.claude/tools/x.py:*)",
        ]
        assert expand_twin_paths(rules=rules, home=_HOME) == rules

    def test_pathless_rules_pass_through(self) -> None:
        rules = ["mcp__plugin_Dev10x_cli__mktmp", "Bash(git status:*)"]
        assert expand_twin_paths(rules=rules, home=_HOME) == rules

    def test_home_trailing_slash_is_normalized(self) -> None:
        rules = ["Read(~/.claude/memory/**)"]
        assert expand_twin_paths(rules=rules, home=_HOME + "/") == [
            "Read(~/.claude/memory/**)",
            "Read(/home/tester/.claude/memory/**)",
        ]

    def test_render_applies_twins_to_all_effect_lists(self) -> None:
        policies = [
            _policy(rule="Read(~/.config/app/**)", effect=PolicyEffect.DENY),
        ]
        rendered = render_permissions(policies=policies, home=_HOME)
        assert rendered["deny"] == [
            "Read(~/.config/app/**)",
            "Read(/home/tester/.config/app/**)",
        ]


class TestParityWithShippedCatalog:
    """PAP-3 AC: renderer output matches the pre-PAP settings lists."""

    def _shipped(self) -> tuple[dict, list[Policy]]:
        from dev10x.skills.permission.policy_catalog_migration import migrate_flat_config

        config = yaml.safe_load(_PROJECTS_YAML.read_text(encoding="utf-8"))
        return config, migrate_flat_config(config=config)

    def test_byte_parity_without_twin_expansion(self) -> None:
        config, policies = self._shipped()
        rendered = render_permissions(policies=policies, home=_HOME, twin_paths=False)
        assert rendered["allow"] == config["base_permissions"]
        assert rendered["deny"] == config["base_denies"]
        assert "ask" not in rendered

    def test_twin_expansion_diffs_are_only_home_twins(self) -> None:
        config, policies = self._shipped()
        rendered = render_permissions(policies=policies, home=_HOME)
        added = [rule for rule in rendered["allow"] if rule not in config["base_permissions"]]
        assert added, "the shipped catalog carries ~/ rules, so twins must appear"
        assert all(f"{_HOME}/" in rule for rule in added)
        removed = [rule for rule in config["base_permissions"] if rule not in rendered["allow"]]
        assert removed == []
