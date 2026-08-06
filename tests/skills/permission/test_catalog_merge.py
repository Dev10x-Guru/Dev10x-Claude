"""Catalog three-way merge (GH-912, ADR-0021).

The defect these cover: the userspace catalog used to *shadow* the
shipped one, so a default shipped after `permission init` was invisible
forever while `ensure-base` reported success against the stale copy.
"""

from __future__ import annotations

import pytest

from dev10x.skills.permission.catalog_merge import (
    CatalogDrift,
    compute_drift,
    format_drift_report,
    merge_catalogs,
)
from dev10x.skills.permission.update_paths import _catalog_drift_messages


@pytest.fixture
def shipped() -> dict:
    return {
        "base_permissions": ["Bash(git status:*)", "Bash(git branch -d:*)"],
        "base_denies": ["Bash(rm -rf:*)"],
        "roots": ["/plugin/root"],
    }


@pytest.fixture
def user() -> dict:
    return {
        "base_permissions": ["Bash(git status:*)", "Bash(uv run pytest:*)"],
        "base_denies": ["Bash(git --no-pager:*)"],
        "roots": ["/home/user/work"],
        "include_user_settings": False,
    }


@pytest.fixture
def merged(shipped: dict, user: dict) -> dict:
    return merge_catalogs(shipped=shipped, user=user).config


@pytest.fixture
def drift(shipped: dict, user: dict) -> CatalogDrift:
    return compute_drift(shipped=shipped, user=user)


def test_shipped_default_absent_from_user_reaches_the_merged_catalog(merged: dict) -> None:
    assert "Bash(git branch -d:*)" in merged["base_permissions"]


def test_user_addition_survives_the_merge(merged: dict) -> None:
    assert "Bash(uv run pytest:*)" in merged["base_permissions"]


def test_shared_rule_is_not_duplicated(merged: dict) -> None:
    assert merged["base_permissions"].count("Bash(git status:*)") == 1


def test_shipped_rules_keep_precedence_in_order(merged: dict) -> None:
    permissions = merged["base_permissions"]
    assert permissions.index("Bash(git branch -d:*)") < permissions.index("Bash(uv run pytest:*)")


def test_denies_from_both_tiers_union(merged: dict) -> None:
    assert set(merged["base_denies"]) == {"Bash(rm -rf:*)", "Bash(git --no-pager:*)"}


def test_machine_specific_keys_stay_user_owned(merged: dict) -> None:
    assert merged["roots"] == ["/home/user/work"]


def test_non_permission_user_keys_pass_through(merged: dict) -> None:
    assert merged["include_user_settings"] is False


def test_drift_names_the_shipped_rule_the_user_lacks(drift: CatalogDrift) -> None:
    assert drift.missing_from_user == ("Bash(git branch -d:*)",)


def test_drift_names_the_user_only_rule(drift: CatalogDrift) -> None:
    assert drift.user_only == ("Bash(uv run pytest:*)",)


def test_drift_flags_missing_defaults(drift: CatalogDrift) -> None:
    assert drift.has_missing_defaults is True


class TestSuppression:
    @pytest.fixture
    def suppressing_user(self, user: dict) -> dict:
        return {**user, "base_permission_suppressions": ["Bash(git branch -d:*)"]}

    def test_suppressed_shipped_rule_is_dropped(
        self, shipped: dict, suppressing_user: dict
    ) -> None:
        merged = merge_catalogs(shipped=shipped, user=suppressing_user).config
        assert "Bash(git branch -d:*)" not in merged["base_permissions"]

    def test_suppressed_rule_is_not_reported_as_missing(
        self, shipped: dict, suppressing_user: dict
    ) -> None:
        drift = compute_drift(shipped=shipped, user=suppressing_user)
        assert drift.missing_from_user == ()

    def test_suppression_is_recorded_for_the_report(
        self, shipped: dict, suppressing_user: dict
    ) -> None:
        drift = compute_drift(shipped=shipped, user=suppressing_user)
        assert drift.suppressed == ("Bash(git branch -d:*)",)


class TestDenySuppressionIsRefused:
    """Denies are the safety floor — ADR-0021 rule 2, GH-925 E6."""

    @pytest.fixture
    def deny_suppressing_user(self, user: dict) -> dict:
        return {**user, "base_permission_suppressions": ["Bash(rm -rf:*)"]}

    def test_shipped_deny_survives_a_suppression_attempt(
        self, shipped: dict, deny_suppressing_user: dict
    ) -> None:
        merged = merge_catalogs(shipped=shipped, user=deny_suppressing_user).config
        assert "Bash(rm -rf:*)" in merged["base_denies"]

    def test_refusal_is_reported(self, shipped: dict, deny_suppressing_user: dict) -> None:
        drift = compute_drift(shipped=shipped, user=deny_suppressing_user)
        assert drift.ignored_deny_suppressions == ("Bash(rm -rf:*)",)

    def test_refused_suppression_is_not_counted_as_an_allow_suppression(
        self, shipped: dict, deny_suppressing_user: dict
    ) -> None:
        drift = compute_drift(shipped=shipped, user=deny_suppressing_user)
        assert drift.suppressed == ()


class TestDegradedInputs:
    def test_missing_user_catalog_yields_shipped_unchanged(self, shipped: dict) -> None:
        assert merge_catalogs(shipped=shipped, user=None).config == shipped

    def test_missing_shipped_catalog_yields_user_unchanged(self, user: dict) -> None:
        assert merge_catalogs(shipped=None, user=user).config == user

    def test_both_missing_yields_empty(self) -> None:
        assert merge_catalogs(shipped=None, user=None).config == {}

    def test_malformed_rule_list_contributes_nothing(self, shipped: dict) -> None:
        merged = merge_catalogs(shipped=shipped, user={"base_permissions": "not-a-list"}).config
        assert merged["base_permissions"] == shipped["base_permissions"]

    def test_non_string_rules_are_skipped(self, shipped: dict) -> None:
        merged = merge_catalogs(shipped=shipped, user={"base_permissions": [42, "Bash(ls:*)"]})
        assert "Bash(ls:*)" in merged.config["base_permissions"]

    def test_drift_against_an_absent_shipped_catalog_reports_user_rules_only(
        self, user: dict
    ) -> None:
        """`catalog-diff` passes ``load_shipped_config()``, which is None
        when the plugin catalog is missing or unreadable."""
        drift = compute_drift(shipped=None, user=user)
        assert drift.missing_from_user == ()
        assert drift.user_only == tuple(user["base_permissions"])


class TestEnsureBaseDriftMessage:
    """`ensure_base` must announce merged-in defaults (GH-925 F1).

    The drift is threaded in rather than re-read, so the message is a
    pure function of its arguments and never touches the real
    `~/.config/Dev10x/projects.yaml`.
    """

    def test_missing_defaults_produce_a_message(self, drift: CatalogDrift) -> None:
        messages = _catalog_drift_messages(drift=drift, quiet=False)
        assert "catalog-diff" in messages[0]

    def test_message_counts_missing_allows_and_denies_together(self, drift: CatalogDrift) -> None:
        messages = _catalog_drift_messages(drift=drift, quiet=False)
        assert "2 shipped rule(s)" in messages[0]

    def test_clean_drift_stays_silent(self) -> None:
        assert _catalog_drift_messages(drift=CatalogDrift(), quiet=False) == []

    def test_absent_drift_stays_silent(self) -> None:
        assert _catalog_drift_messages(drift=None, quiet=False) == []

    def test_quiet_suppresses_the_message(self, drift: CatalogDrift) -> None:
        assert _catalog_drift_messages(drift=drift, quiet=True) == []


class TestDriftReport:
    def test_clean_catalog_reports_in_sync(self) -> None:
        report = format_drift_report(CatalogDrift())
        assert report == ["Catalog is in sync — no drift between shipped and userspace."]

    def test_report_names_the_missing_rule(self, drift: CatalogDrift) -> None:
        assert any("Bash(git branch -d:*)" in line for line in format_drift_report(drift))

    def test_report_explains_the_adr_behaviour_change(self, drift: CatalogDrift) -> None:
        assert any("ADR-0021" in line for line in format_drift_report(drift))
