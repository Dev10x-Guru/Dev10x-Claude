"""DX006 rules live in per-plugin fragments of command-skill-map (GH-1590).

The hook evaluates core's rules first, then each fragment in plugins.yaml
order, and the first match wins. Moving rules between files therefore
changes which rule answers a command that several rules match. The
supervisor accepted that reorder; these tests pin the result, so a later
move that changes a winner fails here instead of shipping silently.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from dev10x.config.loader import fragment_dir, load_config, load_document
from dev10x.domain.rules.rule_engine import RuleEngine
from dev10x.validators.skill_redirect import _YAML_PATH

from dev10x.core.config.fragments import CORE_PLUGIN, discover_fragments, plugin_order

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_SPLIT = REPO_ROOT / "tests" / "fixtures" / "command_skill_map_pre_split.json"

FRAGMENT_RULES = {
    "core": [
        "git-dir-worktree-pinning",
        "python3-inline",
        "bash-n",
        "uv-extra-dev",
        "mktmp-bash-fallback",
        "ci-loop-handrolled",
        "watch-loop-handrolled",
        "for-loop-handrolled",
        "cat-grep-pipeline",
        "find-search",
        "settings-file-read",
        "fish-interactive-abbr",
        "version-pinned-plugin-script",
        "eval-in-skills",
        "sensitive-files",
    ],
    "qa": ["playwright", "qa-evidence-stitch"],
    "infra": ["kubectl", "aws-vault"],
    "db": ["psql-write", "psql"],
    "comm": ["slack-api", "gog-global-flags-first"],
    "coding": [
        "git-commit",
        "gh-pr-create",
        "gh-pr-merge",
        "git-push",
        "git-rebase-interactive",
        "gh-pr-checks-watch",
        "gh-pr-view",
        "gh-issue-close",
        "gh-issue-reopen",
        "gh-issue-view",
        "gh-issue-create",
        "gh-pr-edit",
        "gh-pr-ready",
        "gh-issue-edit",
        "gh-issue-comment",
        "gh-issue-list",
        "gh-pr-list",
        "gh-ci-rerun",
        "gh-milestone-create",
        "gh-milestone-edit",
        "git-push-safe-script",
        "gh-pr-review",
        "pytest-inner-loop",
        "pytest",
        "node-tests-npm-monorepo",
        "node-tests",
        "node-build-scripts",
        "gh-pr-comment-reply",
        "gh-review-threads-graphql",
        "sentry-api",
    ],
}


def rule_digest(*, rule: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:16]


def rule_digests(*, rules: list[dict[str, Any]]) -> dict[str, str]:
    return {rule["name"]: rule_digest(rule=rule) for rule in rules}


def _rule_names(*, path: Path) -> list[str]:
    return [rule["name"] for rule in (yaml.safe_load(path.read_text()) or {}).get("rules", [])]


def _layout() -> dict[str, list[str]]:
    fragments = discover_fragments(
        directories=[fragment_dir(yaml_path=_YAML_PATH)], plugins=plugin_order()
    )
    return {
        CORE_PLUGIN: _rule_names(path=_YAML_PATH),
        **{fragment.plugin: _rule_names(path=fragment.path) for fragment in fragments},
    }


@pytest.fixture(scope="module")
def merged_rules() -> list[dict[str, Any]]:
    return load_document(yaml_path=_YAML_PATH)["rules"]


@pytest.fixture(scope="module")
def pre_split() -> dict[str, Any]:
    return json.loads(PRE_SPLIT.read_text())


class TestLosslessSplit:
    def test_every_rule_body_matches_the_pre_split_map(
        self, merged_rules: list[dict[str, Any]], pre_split: dict[str, Any]
    ) -> None:
        assert rule_digests(rules=merged_rules) == pre_split["digests"]

    def test_no_rule_is_declared_twice(self, merged_rules: list[dict[str, Any]]) -> None:
        names = [rule["name"] for rule in merged_rules]
        assert len(names) == len(set(names))

    def test_the_config_section_stays_in_core(self) -> None:
        assert load_document(yaml_path=_YAML_PATH)["config"]["plugin_repo"]

    def test_fragments_keep_their_pre_split_relative_order(
        self, pre_split: dict[str, Any]
    ) -> None:
        position = {name: index for index, name in enumerate(pre_split["order"])}
        orders = {
            plugin: sorted(names, key=position.__getitem__) for plugin, names in _layout().items()
        }
        assert orders == _layout()


def test_fragment_layout_is_pinned() -> None:
    assert _layout() == FRAGMENT_RULES


@pytest.fixture(scope="module")
def hook_engine() -> RuleEngine:
    return RuleEngine.from_config(config=load_config(yaml_path=_YAML_PATH))


@pytest.fixture(scope="module")
def all_bash_rules_engine() -> RuleEngine:
    config = load_config(yaml_path=_YAML_PATH)
    return RuleEngine(command_rules=[rule for rule in config.rules if rule.matcher == "Bash"])


#: (command, winner among hook_block rules, winner among all Bash rules)
WINNERS = [
    (
        'while true; do psql -c "DELETE FROM t"; sleep 5; done',
        "watch-loop-handrolled",
        "watch-loop-handrolled",
    ),
    ('aws-vault exec prod -- psql -c "select 1"', None, "aws-vault"),
    ('aws-vault exec prod -- psql -c "DELETE FROM t"', "psql-write", "aws-vault"),
    ('kubectl exec pod -- psql -c "DELETE FROM t"', "psql-write", "kubectl"),
    ("npx playwright test", None, "playwright"),
    ("pnpm run test:e2e", None, "node-tests"),
    ("git --git-dir=/x/.git commit -m x", "git-dir-worktree-pinning", "git-dir-worktree-pinning"),
    ("while true; do git push; sleep 1; done", "watch-loop-handrolled", "watch-loop-handrolled"),
    ("while true; do gh pr checks 1; sleep 30; done", "ci-loop-handrolled", "ci-loop-handrolled"),
    ("uv run --extra dev pytest -k x", "pytest-inner-loop", "uv-extra-dev"),
    # Further overlaps whose winner the split moved off a coding rule.
    ("for b in x y; do git push origin $b; done", "git-push", "for-loop-handrolled"),
    ("gh pr view 1 && sleep 30", "ci-loop-handrolled", "ci-loop-handrolled"),
    ("aws-vault exec prod -- gh pr view 1", "gh-pr-view", "aws-vault"),
    ("psql -f seed.sql; git push", "psql-write", "psql-write"),
    (
        "~/.claude/plugins/cache/Dev10x-Guru/dev10x/0.108.0/skills/git/scripts/git-push-safe.sh",
        "git-push-safe-script",
        "git-push-safe-script",
    ),
]


@pytest.mark.parametrize(("command", "hook_winner", "_all_winner"), WINNERS)
def test_hook_winner_is_pinned(
    hook_engine: RuleEngine, command: str, hook_winner: str | None, _all_winner: str
) -> None:
    rule = hook_engine.evaluate_command(command=command)
    assert getattr(rule, "name", None) == hook_winner


@pytest.mark.parametrize(("command", "_hook_winner", "all_winner"), WINNERS)
def test_first_match_over_every_rule_is_pinned(
    all_bash_rules_engine: RuleEngine, command: str, _hook_winner: str | None, all_winner: str
) -> None:
    rule = all_bash_rules_engine.evaluate_command(command=command)
    assert rule is not None
    assert rule.name == all_winner
