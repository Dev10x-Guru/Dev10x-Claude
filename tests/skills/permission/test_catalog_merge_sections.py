"""Every shipped-content section merges, not just allow and deny.

GH-1249: ``merge_catalogs`` merged ``base_permissions`` and
``base_denies`` and let every other key pass through from the user's
catalog. That was right for the machine-specific keys it was written
for and silently wrong for ``base_asks`` (shipped by GH-1149) and
``tracker_permissions`` / ``tracker_denies`` (shipped by GH-768): a
catalog created before those keys existed never received them.

The observed cost on a live machine: zero ``ask`` rules reached any
settings file, and a repo pinned ``tracker: github`` was seeded with no
github tracker rules while stale inline Linear rules persisted. Every
rule-level check reported clean, because a section the user's catalog
does not declare is a section nothing compares against.

The fixture below is that machine's other catalog verbatim in shape —
``~/.config/Dev10x/upgrade-cleanup-projects.yaml``, which carries only
four keys and becomes the effective catalog wherever the newer file is
absent.
"""

from __future__ import annotations

import logging

import pytest

from dev10x.skills.permission.catalog_merge import (
    ASK_KEY,
    IDE_ALLOW_KEY,
    IDE_DENY_KEY,
    MERGED_LIST_KEYS,
    MERGED_TRACKER_KEYS,
    TRACKER_ALLOW_KEY,
    TRACKER_DENY_KEY,
    USER_OWNED_KEYS,
    compute_drift,
    format_drift_report,
    merge_catalogs,
    unclassified_shipped_keys,
)

SHIPPED = {
    "plugin_cache": "~/.claude/plugins/cache/Dev10x-Guru/Dev10x",
    "roots": [],
    "include_user_settings": True,
    "workspace_directories": ["/tmp/Dev10x"],
    "base_permissions": ["Bash(gh pr view:*)"],
    "base_asks": ["Bash(gh api -X DELETE:*)"],
    "base_denies": ["Bash(sudo:*)"],
    "tracker_permissions": {
        "github": ["mcp__plugin_Dev10x_cli__issue_close"],
        "linear": ["mcp__claude_ai_Linear__get_issue"],
    },
    "tracker_denies": {"linear": ["mcp__claude_ai_Linear__delete_comment"]},
    "ide_permissions": {"pycharm": ["mcp__pycharm__get_file_problems"]},
    "ide_denies": {"pycharm": ["mcp__pycharm__execute_terminal_command"]},
}

# A catalog written before GH-768 and GH-1149: no ask tier, no tracker
# sections, and its own machine-specific values.
PRE_SECTIONS_USER = {
    "plugin_cache": "~/.claude/plugins/cache/Dev10x-Guru/Dev10x",
    "roots": ["/work/tt"],
    "include_user_settings": True,
    "base_permissions": ["Bash(gog --version)"],
}


def _merged(user: dict) -> dict:
    return merge_catalogs(shipped=SHIPPED, user=user).config


@pytest.mark.parametrize("key", MERGED_LIST_KEYS)
def test_shipped_list_sections_reach_a_catalog_that_lacks_them(key: str) -> None:
    assert SHIPPED[key][0] in _merged(PRE_SECTIONS_USER)[key]


@pytest.mark.parametrize("key", MERGED_TRACKER_KEYS)
def test_shipped_tracker_sections_reach_a_catalog_that_lacks_them(key: str) -> None:
    merged = _merged(PRE_SECTIONS_USER)[key]
    for tracker, rules in SHIPPED[key].items():
        assert set(rules) <= set(merged[tracker])


def test_github_pinned_repo_receives_the_github_tracker_block() -> None:
    """The concrete GH-1249 symptom, stated as its own case."""
    merged = _merged(PRE_SECTIONS_USER)[TRACKER_ALLOW_KEY]
    assert "mcp__plugin_Dev10x_cli__issue_close" in merged["github"]


@pytest.mark.parametrize("key", USER_OWNED_KEYS)
def test_user_owned_keys_are_not_merged(key: str) -> None:
    """Machine-specific keys keep the user's value (ADR-0021 rule 3)."""
    user = {**PRE_SECTIONS_USER, key: "user-value"}
    assert _merged(user)[key] == "user-value"


def test_user_roots_survive_the_merge() -> None:
    assert _merged(PRE_SECTIONS_USER)["roots"] == ["/work/tt"]


def test_user_only_rules_survive_the_merge() -> None:
    assert "Bash(gog --version)" in _merged(PRE_SECTIONS_USER)["base_permissions"]


def test_missing_sections_are_reported() -> None:
    drift = compute_drift(shipped=SHIPPED, user=PRE_SECTIONS_USER)
    assert set(drift.missing_sections) == {
        ASK_KEY,
        TRACKER_ALLOW_KEY,
        TRACKER_DENY_KEY,
        IDE_ALLOW_KEY,
        IDE_DENY_KEY,
        "base_denies",
    }


def test_missing_sections_count_as_missing_defaults() -> None:
    """A wholly-absent section must not read as a clean catalog."""
    drift = compute_drift(shipped=SHIPPED, user=PRE_SECTIONS_USER)
    assert drift.has_missing_defaults
    assert not drift.is_clean


def test_a_current_catalog_reports_no_missing_sections() -> None:
    drift = compute_drift(shipped=SHIPPED, user=dict(SHIPPED))
    assert drift.missing_sections == ()


def test_tracker_absent_from_shipped_is_carried_through() -> None:
    """A user's own tracker entry is not dropped by the merge."""
    user = {**PRE_SECTIONS_USER, TRACKER_ALLOW_KEY: {"jira": ["mcp__x__y"]}}
    merged = _merged(user)[TRACKER_ALLOW_KEY]
    assert merged["jira"] == ["mcp__x__y"]
    assert "mcp__plugin_Dev10x_cli__issue_close" in merged["github"]


def test_ask_rules_accept_suppression() -> None:
    """An ask is a prompt, not a grant — a user may silence one."""
    user = {
        **PRE_SECTIONS_USER,
        "base_permission_suppressions": ["Bash(gh api -X DELETE:*)"],
    }
    assert _merged(user)[ASK_KEY] == []


def test_tracker_denies_refuse_suppression() -> None:
    """Deny tiers are the safety floor, tracker denies included."""
    rule = "mcp__claude_ai_Linear__delete_comment"
    user = {**PRE_SECTIONS_USER, "base_permission_suppressions": [rule]}
    assert rule in _merged(user)[TRACKER_DENY_KEY]["linear"]

    drift = compute_drift(shipped=SHIPPED, user=user)
    assert rule in drift.ignored_deny_suppressions
    assert rule not in drift.suppressed


def test_pre_gh1261_catalog_receives_the_ide_permission_block() -> None:
    """GH-1311: a catalog predating GH-1261 has no IDE keys at all.

    Before the fix, ``ide_permissions``/``ide_denies`` were classified
    in neither the merge set nor ``USER_OWNED_KEYS``, so they never
    reached a catalog written before GH-1261 shipped them.
    """
    merged = _merged(PRE_SECTIONS_USER)
    assert "mcp__pycharm__get_file_problems" in merged[IDE_ALLOW_KEY]["pycharm"]
    assert "mcp__pycharm__execute_terminal_command" in merged[IDE_DENY_KEY]["pycharm"]


def test_ide_denies_refuse_suppression() -> None:
    """GH-1261's shell-equivalent-tool denies are unconditional.

    A user catalog must not be able to suppress them back out, the same
    guarantee ``tracker_denies`` already carries.
    """
    rule = "mcp__pycharm__execute_terminal_command"
    user = {**PRE_SECTIONS_USER, "base_permission_suppressions": [rule]}
    assert rule in _merged(user)[IDE_DENY_KEY]["pycharm"]

    drift = compute_drift(shipped=SHIPPED, user=user)
    assert rule in drift.ignored_deny_suppressions
    assert rule not in drift.suppressed


def test_ide_keys_no_longer_reported_as_unclassified() -> None:
    """The GH-1311 symptom: the warning fired on every invocation."""
    assert IDE_ALLOW_KEY not in unclassified_shipped_keys(SHIPPED)
    assert IDE_DENY_KEY not in unclassified_shipped_keys(SHIPPED)


def test_ide_keys_do_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        merge_catalogs(shipped=SHIPPED, user=PRE_SECTIONS_USER)
    assert "ide_permissions" not in caplog.text
    assert "ide_denies" not in caplog.text


def test_ide_drift_renders_in_the_report() -> None:
    """A pre-GH-1261 catalog's missing IDE section and rules both print."""
    drift = compute_drift(shipped=SHIPPED, user=PRE_SECTIONS_USER)
    report = format_drift_report(drift)
    assert any("shipped SECTIONS absent from userspace" in line for line in report)
    assert any(IDE_ALLOW_KEY in line for line in report)
    assert any(IDE_DENY_KEY in line for line in report)
    assert any("shipped IDE rules missing from userspace" in line for line in report)
    assert any("shipped IDE denies missing from userspace" in line for line in report)
    assert any("mcp__pycharm__get_file_problems" in line for line in report)
    assert any("mcp__pycharm__execute_terminal_command" in line for line in report)


def test_unclassified_shipped_key_is_named() -> None:
    """The guard against repeating GH-1249 with the next new key."""
    assert unclassified_shipped_keys({**SHIPPED, "base_something_new": []}) == (
        "base_something_new",
    )


def test_unclassified_shipped_key_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        merge_catalogs(shipped={**SHIPPED, "base_something_new": []}, user=PRE_SECTIONS_USER)
    assert "base_something_new" in caplog.text


def test_every_shipped_key_is_classified() -> None:
    """The real shipped catalog must have no unclassified keys.

    This is the test that would have caught GH-1249 when GH-768 and
    GH-1149 added their sections.
    """
    assert unclassified_shipped_keys(SHIPPED) == ()
