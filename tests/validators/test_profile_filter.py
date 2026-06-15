"""Tests for profile-tier filtering in the validator registry (GH-413).

Verifies DEV10X_HOOK_PROFILE, DEV10X_HOOK_DISABLE, and
DEV10X_HOOK_EXPERIMENTAL env vars control which validators run.
"""

from __future__ import annotations

import pytest

from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators import (
    _load_profile_config,
    get_validators,
    reset_registry,
)


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Reset the cached validator registry around each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear profile-related env vars for deterministic tests."""
    monkeypatch.delenv("DEV10X_HOOK_PROFILE", raising=False)
    monkeypatch.delenv("DEV10X_HOOK_DISABLE", raising=False)
    monkeypatch.delenv("DEV10X_HOOK_EXPERIMENTAL", raising=False)


class TestLoadProfileConfig:
    def test_defaults_to_standard(self) -> None:
        active, disabled, experimental = _load_profile_config()
        assert active is ProfileTier.STANDARD
        assert disabled == set()
        assert experimental is False

    def test_reads_profile_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "minimal")
        active, _, _ = _load_profile_config()
        assert active is ProfileTier.MINIMAL

    def test_invalid_profile_falls_back_to_standard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "paranoid")
        active, _, _ = _load_profile_config()
        assert active is ProfileTier.STANDARD

    def test_disable_list_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX001, dx002,DX003 ")
        _, disabled, _ = _load_profile_config()
        assert disabled == {"DX001", "DX002", "DX003"}

    def test_disable_list_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "")
        _, disabled, _ = _load_profile_config()
        assert disabled == set()

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_experimental_enabled_values(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", value)
        _, _, experimental = _load_profile_config()
        assert experimental is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_experimental_disabled_values(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("DEV10X_HOOK_EXPERIMENTAL", value)
        _, _, experimental = _load_profile_config()
        assert experimental is False


class TestGetValidatorsProfileFiltering:
    def test_default_profile_is_standard(self) -> None:
        validators = get_validators()
        allowed = {ProfileTier.MINIMAL, ProfileTier.STANDARD}
        assert all(v.profile in allowed for v in validators), (
            f"Unexpected profiles: {[v.profile for v in validators]}"
        )

    def test_minimal_profile_excludes_standard_and_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "minimal")
        validators = get_validators()
        assert all(v.profile is ProfileTier.MINIMAL for v in validators)
        # Should include skill_redirect only at standard+, so it's excluded here
        names = {v.name for v in validators}
        assert "skill-redirect" not in names

    def test_strict_profile_includes_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "strict")
        validators = get_validators()
        names = {v.name for v in validators}
        # commit-jtbd is the strict-only validator
        assert "commit-jtbd" in names
        assert "skill-redirect" in names
        assert "safe-subshell" in names


class TestGetValidatorsDisableFiltering:
    def test_disable_single_rule(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX001")
        validators = get_validators()
        names = {v.name for v in validators}
        assert "safe-subshell" not in names

    def test_disable_multiple_rules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX001,DX006")
        validators = get_validators()
        names = {v.name for v in validators}
        assert "safe-subshell" not in names
        assert "skill-redirect" not in names

    def test_disable_is_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "dx001")
        validators = get_validators()
        names = {v.name for v in validators}
        assert "safe-subshell" not in names

    def test_disable_unknown_rule_id_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX999")
        validators = get_validators()
        assert len(validators) > 0


class TestRuleIdAssignment:
    def test_every_validator_has_rule_id(self) -> None:
        validators = get_validators()
        missing = [type(v).__name__ for v in validators if not hasattr(v, "rule_id")]
        assert not missing, f"Validators missing rule_id: {missing}"
        non_dx = [v.rule_id for v in validators if not v.rule_id.startswith("DX")]
        assert not non_dx, f"rule_ids not starting with DX: {non_dx}"

    def test_every_validator_has_profile(self) -> None:
        validators = get_validators()
        missing = [type(v).__name__ for v in validators if not hasattr(v, "profile")]
        assert not missing, f"Validators missing profile: {missing}"
        non_tier = [type(v).__name__ for v in validators if not isinstance(v.profile, ProfileTier)]
        assert not non_tier, f"Validators with non-ProfileTier profile: {non_tier}"

    def test_rule_ids_are_unique(self) -> None:
        # Use strict profile to get all validators
        import os

        os.environ["DEV10X_HOOK_PROFILE"] = "strict"
        try:
            reset_registry()
            validators = get_validators()
            rule_ids = [v.rule_id for v in validators]
            assert len(rule_ids) == len(set(rule_ids)), f"Duplicate rule_ids: {rule_ids}"
        finally:
            del os.environ["DEV10X_HOOK_PROFILE"]
            reset_registry()
