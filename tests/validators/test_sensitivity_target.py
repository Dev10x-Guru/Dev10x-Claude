"""Tests for SensitivityTargetValidator (DX014).

Covers:
- should_run() fast-skip predicate
- validate() returning None for benign commands
- validate() returning HookResult for each sensitivity label
- deny-overrides semantics: multi-match accumulates all matches
- Registry integration: DX014 appears in standard profile
- Custom classifier injection via with_patterns()

Fixtures are drawn from GH-271 evidence #267–#273 (same corpus as
the SensitivityClassifier unit tests in tests/domain/test_sensitivity.py).
"""

from __future__ import annotations

import pytest

from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.sensitivity import SensitivityClassifier, SensitivityLabel, SensitivityPattern
from dev10x.validators import get_validators, reset_registry
from dev10x.validators.sensitivity_target import SensitivityTargetValidator
from tests.fakers import BashHookInputFaker


def _inp(command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(command=command)


# ---------------------------------------------------------------------------
# Fixture: default validator instance
# ---------------------------------------------------------------------------


@pytest.fixture()
def validator() -> SensitivityTargetValidator:
    return SensitivityTargetValidator()


# ---------------------------------------------------------------------------
# should_run
# ---------------------------------------------------------------------------


class TestShouldRun:
    def test_empty_command_skips(self, validator: SensitivityTargetValidator) -> None:
        assert validator.should_run(inp=_inp("")) is False

    def test_whitespace_only_skips(self, validator: SensitivityTargetValidator) -> None:
        assert validator.should_run(inp=_inp("   ")) is False

    def test_non_empty_command_runs(self, validator: SensitivityTargetValidator) -> None:
        assert validator.should_run(inp=_inp("git status")) is True

    def test_sensitive_command_runs(self, validator: SensitivityTargetValidator) -> None:
        assert validator.should_run(inp=_inp("gh secret list")) is True


# ---------------------------------------------------------------------------
# validate() — benign commands → None
# ---------------------------------------------------------------------------


class TestBenignCommands:
    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git log --oneline -10",
            "ls -la",
            "uv run pytest tests/",
            "ruff check src/",
            "git diff origin/develop",
            "gh pr view 42",
            "find . -name '*.py'",
        ],
    )
    def test_benign_commands_return_none(
        self, validator: SensitivityTargetValidator, command: str
    ) -> None:
        result = validator.validate(inp=_inp(command))
        assert result is None, f"Unexpected block for benign command: {command!r}"


# ---------------------------------------------------------------------------
# validate() — SECRET label
# ---------------------------------------------------------------------------


class TestSecretLabel:
    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 #267: secret inventory
            "gh secret list",
            "gh secret list --repo my-org/my-repo",
            "gh variable list",
            "gh variable get MY_VAR",
            # kubectl secret
            "kubectl get secret db-credentials -o yaml",
            "kubectl describe secret my-secret",
            # .env reads
            "cat .env",
            "cat /app/.env",
            "less .env",
            "head -20 .env",
        ],
    )
    def test_blocks_secret_commands(
        self, validator: SensitivityTargetValidator, command: str
    ) -> None:
        result = validator.validate(inp=_inp(command))
        assert result is not None, f"Expected block for: {command!r}"
        assert "SECRET" in result.message

    def test_message_contains_pattern_description(
        self, validator: SensitivityTargetValidator
    ) -> None:
        result = validator.validate(inp=_inp("gh secret list"))
        assert result is not None
        assert "gh secret" in result.message

    def test_message_contains_matched_text(self, validator: SensitivityTargetValidator) -> None:
        result = validator.validate(inp=_inp("gh secret list"))
        assert result is not None
        assert "matched:" in result.message


# ---------------------------------------------------------------------------
# validate() — CREDENTIAL label
# ---------------------------------------------------------------------------


class TestCredentialLabel:
    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 #269: searching for RW credentials
            "rg PRODUCTION_RW .env",
            "grep -r DB_PASSWORD src/",
            "export DB_URL=postgres://...",
            "env | grep API_TOKEN",
            "echo $JWT_SECRET",
            # general credential env-var patterns
            "printenv | grep SSH_PRIVATE_KEY",
        ],
    )
    def test_blocks_credential_commands(
        self, validator: SensitivityTargetValidator, command: str
    ) -> None:
        result = validator.validate(inp=_inp(command))
        assert result is not None, f"Expected block for: {command!r}"
        assert "CREDENTIAL" in result.message

    def test_rw_suffix_blocked(self, validator: SensitivityTargetValidator) -> None:
        result = validator.validate(inp=_inp("echo $DATABASE_RW"))
        assert result is not None
        assert "CREDENTIAL" in result.message


# ---------------------------------------------------------------------------
# validate() — PII label
# ---------------------------------------------------------------------------


class TestPiiLabel:
    @pytest.mark.parametrize(
        "command",
        [
            # PII bulk-export patterns
            "pg_dump --table customers mydb",
            "mysqldump mydb patients",
            "SELECT * FROM customers",
            "SELECT * FROM subscribers",
        ],
    )
    def test_blocks_pii_commands(
        self, validator: SensitivityTargetValidator, command: str
    ) -> None:
        result = validator.validate(inp=_inp(command))
        assert result is not None, f"Expected block for: {command!r}"
        assert "PII" in result.message


# ---------------------------------------------------------------------------
# validate() — INFRA label
# ---------------------------------------------------------------------------


class TestInfraLabel:
    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 #271: RDS endpoint resolution
            "dig writer.mydb.us-east-1.rds.amazonaws.com",
            # GH-271 #272–#273: nc port probes
            "nc -zv 10.0.0.5 5432",
            "nc -zvw5 prod-db.internal 3306",
            # bastion/VPN
            "ssh bastion.prod.internal",
            "wg show wireguard0",
            "tailscale status",
        ],
    )
    def test_blocks_infra_commands(
        self, validator: SensitivityTargetValidator, command: str
    ) -> None:
        result = validator.validate(inp=_inp(command))
        assert result is not None, f"Expected block for: {command!r}"
        assert "INFRA" in result.message

    def test_rds_hostname_in_connection_string(
        self, validator: SensitivityTargetValidator
    ) -> None:
        cmd = "psql postgres://user:pass@writer.cluster.us-east-1.rds.amazonaws.com/mydb"
        result = validator.validate(inp=_inp(cmd))
        assert result is not None
        assert "INFRA" in result.message


# ---------------------------------------------------------------------------
# Deny-overrides: multi-label accumulation
# ---------------------------------------------------------------------------


class TestDenyOverrides:
    def test_multi_label_match_reports_all(self, validator: SensitivityTargetValidator) -> None:
        # Command that hits both CREDENTIAL and INFRA axes simultaneously.
        cmd = "rg DB_PASSWORD 10.0.0.5"
        result = validator.validate(inp=_inp(cmd))
        assert result is not None
        # Both labels must appear in the message.
        assert "CREDENTIAL" in result.message
        assert "INFRA" in result.message

    def test_match_count_in_message(self, validator: SensitivityTargetValidator) -> None:
        cmd = "cat .env && nc -zv 10.0.0.5 5432"
        result = validator.validate(inp=_inp(cmd))
        assert result is not None
        # The count line must show > 1.
        import re

        count_match = re.search(r"matched (\d+) sensitivity pattern", result.message)
        assert count_match is not None
        assert int(count_match.group(1)) > 1

    def test_block_regardless_of_tier_reversibility(
        self, validator: SensitivityTargetValidator
    ) -> None:
        # A read-only safe command that is nonetheless sensitive.
        result = validator.validate(inp=_inp("gh secret list"))
        assert result is not None, (
            "Sensitivity axis must override tier/reversibility (deny-overrides)"
        )


# ---------------------------------------------------------------------------
# Message format checks
# ---------------------------------------------------------------------------


class TestMessageFormat:
    def test_message_mentions_review(self, validator: SensitivityTargetValidator) -> None:
        result = validator.validate(inp=_inp("gh secret list"))
        assert result is not None
        assert "review" in result.message.lower()

    def test_message_references_hook_patterns(self, validator: SensitivityTargetValidator) -> None:
        result = validator.validate(inp=_inp("gh secret list"))
        assert result is not None
        assert "hook-patterns.md" in result.message

    def test_message_references_rule_id(self, validator: SensitivityTargetValidator) -> None:
        result = validator.validate(inp=_inp("gh secret list"))
        assert result is not None
        assert "DX014" in result.message


# ---------------------------------------------------------------------------
# Custom classifier injection
# ---------------------------------------------------------------------------


class TestCustomClassifier:
    def test_custom_wordlist_replaces_default(self) -> None:
        import re

        custom_pattern = SensitivityPattern(
            label=SensitivityLabel.SECRET,
            regex=re.compile(r"\bcustom_secret_tool\b"),
            description="custom secret tool",
        )
        custom_classifier = SensitivityClassifier(patterns=[custom_pattern])
        v = SensitivityTargetValidator(classifier=custom_classifier)

        # Default wordlist pattern should NOT fire.
        assert v.validate(inp=_inp("gh secret list")) is None

        # Custom pattern SHOULD fire.
        result = v.validate(inp=_inp("custom_secret_tool --list"))
        assert result is not None
        assert "SECRET" in result.message

    def test_with_patterns_factory(self) -> None:
        import re

        base = SensitivityTargetValidator()
        custom = base.with_patterns(
            patterns=[
                SensitivityPattern(
                    label=SensitivityLabel.PII,
                    regex=re.compile(r"\bmy_pii_table\b"),
                    description="my_pii_table",
                )
            ]
        )
        # Original still uses default patterns.
        assert base.validate(inp=_inp("gh secret list")) is not None
        # Custom uses injected patterns only.
        assert custom.validate(inp=_inp("gh secret list")) is None
        result = custom.validate(inp=_inp("SELECT * FROM my_pii_table"))
        assert result is not None
        assert "PII" in result.message


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    reset_registry()
    yield
    reset_registry()


class TestRegistryIntegration:
    def test_dx014_registered_in_standard_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DEV10X_HOOK_PROFILE", raising=False)
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX014" in rule_ids

    def test_dx014_absent_in_minimal_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "minimal")
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX014" not in rule_ids

    def test_dx014_present_in_strict_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "strict")
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX014" in rule_ids

    def test_dx014_can_be_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX014")
        validators = get_validators()
        rule_ids = {v.rule_id for v in validators}
        assert "DX014" not in rule_ids

    def test_validator_instance_is_sensitivity_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEV10X_HOOK_PROFILE", raising=False)
        validators = get_validators()
        sensitivity_validators = [v for v in validators if v.rule_id == "DX014"]
        assert len(sensitivity_validators) == 1
        assert isinstance(sensitivity_validators[0], SensitivityTargetValidator)

    def test_validator_profile_is_standard(self) -> None:
        v = SensitivityTargetValidator()
        assert v.profile is ProfileTier.STANDARD

    def test_rule_ids_remain_unique(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEV10X_HOOK_PROFILE", "strict")
        validators = get_validators()
        rule_ids = [v.rule_id for v in validators]
        assert len(rule_ids) == len(set(rule_ids)), f"Duplicate rule_ids: {rule_ids}"
