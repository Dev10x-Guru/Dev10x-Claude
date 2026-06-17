"""Tests for the sensitivity axis model (GH-395).

Fixtures are drawn directly from GH-271 evidence entries #267–#273,
which document the sequence: discover credentials → discover pivot →
resolve endpoint → probe DB ports.  Each step was individually
tier=safe-read and reversibility=trivial, yet plainly sensitive.
"""

from __future__ import annotations

import pytest

from dev10x.domain.sensitivity import (
    SENSITIVE_NAME_TOKENS,
    SensitivityClassifier,
    SensitivityLabel,
    SensitivityMatch,
    SensitivityPattern,
    name_is_sensitive,
    tokenize_identifier,
)

# ---------------------------------------------------------------------------
# SensitivityLabel
# ---------------------------------------------------------------------------


class TestSensitivityLabel:
    def test_all_four_labels_exist(self) -> None:
        labels = {label.value for label in SensitivityLabel}
        assert labels == {"secret", "credential", "pii", "infra"}

    @pytest.mark.parametrize("label", list(SensitivityLabel), ids=lambda lbl: lbl.name)
    def test_value_is_lowercase_string(self, label: SensitivityLabel) -> None:
        assert label.value == label.value.lower()

    def test_repr_includes_name(self) -> None:
        assert "SECRET" in repr(SensitivityLabel.SECRET)


# ---------------------------------------------------------------------------
# SensitivityClassifier — SECRET label
# ---------------------------------------------------------------------------


class TestSecretClassification:
    @pytest.fixture()
    def classifier(self) -> SensitivityClassifier:
        return SensitivityClassifier()

    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 #267: inventory of secrets
            "gh secret list",
            "gh secret list --repo my-org/my-repo",
            # gh variable is also secret-scoped
            "gh variable list",
            "gh variable get MY_VAR",
            # kubectl secret access
            "kubectl get secret db-credentials -o yaml",
            "kubectl describe secret my-secret",
        ],
    )
    def test_secret_commands_classified_as_secret(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.SECRET in labels, f"Expected SECRET for: {command!r}"

    @pytest.mark.parametrize(
        "command",
        [
            # .env file reads
            "cat .env",
            "cat /app/.env",
            "less .env",
            "head -20 .env",
        ],
    )
    def test_env_file_reads_classified_as_secret(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.SECRET in labels, f"Expected SECRET for: {command!r}"

    @pytest.mark.parametrize(
        "command",
        [
            # GH-605: credentialed-CLI secret-exfil reads
            "aws-vault exec prod -- aws secretsmanager get-secret-value --secret-id db",
            "aws-vault exec prod -- aws ssm get-parameter --name /db/pw --with-decryption",
            "aws ssm get-parameters --names /db/pw --with-decryption",
            "vercel env pull .env.local",
            "vercel pull",
        ],
    )
    def test_credentialed_cli_exfil_classified_as_secret(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.SECRET in labels, f"Expected SECRET for: {command!r}"

    @pytest.mark.parametrize(
        "command",
        [
            # GH-605: benign credentialed-CLI reads must NOT be flagged secret
            "aws-vault exec prod -- aws ecr describe-images --repository-name app",
            "aws-vault exec prod -- aws s3 ls",
            "aws ssm get-parameter --name /db/host",  # no --with-decryption
            "vercel ls",
        ],
    )
    def test_benign_credentialed_reads_not_secret(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        assert not any(m.label == SensitivityLabel.SECRET for m in matches), (
            f"Benign read wrongly flagged SECRET: {command!r}"
        )

    def test_benign_gh_pr_not_secret(self, classifier: SensitivityClassifier) -> None:
        matches = classifier.classify(command="gh pr list")
        assert not any(m.label == SensitivityLabel.SECRET for m in matches)

    def test_kubectl_get_pods_not_secret(self, classifier: SensitivityClassifier) -> None:
        matches = classifier.classify(command="kubectl get pods")
        assert not any(m.label == SensitivityLabel.SECRET for m in matches)


# ---------------------------------------------------------------------------
# SensitivityClassifier — CREDENTIAL label
# ---------------------------------------------------------------------------


class TestCredentialClassification:
    @pytest.fixture()
    def classifier(self) -> SensitivityClassifier:
        return SensitivityClassifier()

    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 #269: rg for PRODUCTION_RW credential pattern
            "rg PRODUCTION_RW /work/tt",
            "grep -r APP_PRODUCTION_RW .",
            # Generic _RW suffix
            "grep DB_STAGING_RW .env",
            # Common credential suffixes
            "env | grep DB_PASSWORD",
            "echo $API_TOKEN",
            "printenv APP_SECRET",
            "printenv JWT_PRIVATE_KEY",
            # GH-271 #270: ~/.config scan for credentials
            "rg ~/.config --glob '*.yaml' password",
        ],
    )
    def test_credential_commands_classified(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.CREDENTIAL in labels, f"Expected CREDENTIAL for: {command!r}"

    @pytest.mark.parametrize(
        "command",
        [
            "export DB_URL=postgres://localhost/dev",
            "export DB_PASSWORD=mysecret",
        ],
    )
    def test_export_db_classified_as_credential(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.CREDENTIAL in labels

    def test_benign_ls_not_credential(self, classifier: SensitivityClassifier) -> None:
        matches = classifier.classify(command="ls -la /tmp")
        assert not any(m.label == SensitivityLabel.CREDENTIAL for m in matches)

    def test_short_rw_suffix_not_matched(self, classifier: SensitivityClassifier) -> None:
        # Single-char or two-char prefixes like "RW" alone shouldn't fire
        matches = classifier.classify(command="chmod +rw /tmp/file")
        assert not any(m.label == SensitivityLabel.CREDENTIAL for m in matches)


# ---------------------------------------------------------------------------
# SensitivityClassifier — INFRA label
# ---------------------------------------------------------------------------


class TestInfraClassification:
    @pytest.fixture()
    def classifier(self) -> SensitivityClassifier:
        return SensitivityClassifier()

    @pytest.mark.parametrize(
        "command",
        [
            # GH-271 #271: dig on production RDS writer endpoint
            "dig mydb.cluster-abc123.us-east-1.rds.amazonaws.com",
            # GH-271 #272–#273: nc probes to production DB ports
            "nc -zv 10.0.0.5 5432",
            "nc -zvw3 192.168.1.100 5432",
            # bastion / VPN hosts
            "ssh bastion.internal",
            "wg show wireguard0",
            "cloudflared tunnel list",
            "tailscale status",
            # production hostnames
            "curl https://prod.myapp.example.com/health",
            "ping production.db.internal",
            # GH-482: real prod host via user@ and dotted FQDN still fire
            "ssh deploy@prod-web01.example.com",
            "psql -h prod-db.acme.internal -U app",
            # RFC 1918 private IPs
            "curl http://10.0.1.42/api",
            "ssh 172.16.0.10",
            "ping 192.168.100.5",
        ],
    )
    def test_infra_commands_classified(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.INFRA in labels, f"Expected INFRA for: {command!r}"

    @pytest.mark.parametrize(
        "command",
        [
            "curl https://api.github.com/repos",
            "ping localhost",
            "curl http://127.0.0.1:8000/health",
            "git push origin develop",
            # GH-482: `prod-` in filenames, branch slugs, and grep
            # literals must NOT trip the production-host pattern.
            "yq '.' .github/workflows/prod-synthetic.yml",
            "pre-commit run --files .github/workflows/prod-synthetic.yml",
            "grep -rln 'purge-prod-synthetic' .github/workflows/",
            "git checkout -b wonka/CANDY-935/prod-synthetic-cohesion origin/develop",
            "gh workflow run prod-synthetic.yml",
        ],
    )
    def test_safe_network_commands_not_infra(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        assert not any(m.label == SensitivityLabel.INFRA for m in matches), (
            f"Expected no INFRA match for: {command!r}"
        )


# ---------------------------------------------------------------------------
# SensitivityClassifier — PII label
# ---------------------------------------------------------------------------


class TestPiiClassification:
    @pytest.fixture()
    def classifier(self) -> SensitivityClassifier:
        return SensitivityClassifier()

    @pytest.mark.parametrize(
        "command",
        [
            # pg_dump / mysqldump against a PII table name
            "pg_dump customers --table=customers > dump.sql",
            "mysqldump customers --single-transaction",
            # SELECT * queries against PII tables (bulk read)
            "SELECT * FROM customers LIMIT 100",
            "SELECT * FROM patients WHERE active=1",
        ],
    )
    def test_customer_data_dumps_classified_as_pii(
        self, classifier: SensitivityClassifier, command: str
    ) -> None:
        matches = classifier.classify(command=command)
        labels = {m.label for m in matches}
        assert SensitivityLabel.PII in labels, f"Expected PII for: {command!r}"

    def test_benign_select_not_pii(self, classifier: SensitivityClassifier) -> None:
        matches = classifier.classify(command="SELECT id, name FROM products LIMIT 10")
        assert not any(m.label == SensitivityLabel.PII for m in matches)


# ---------------------------------------------------------------------------
# SensitivityClassifier — helper methods
# ---------------------------------------------------------------------------


class TestClassifierHelpers:
    @pytest.fixture()
    def classifier(self) -> SensitivityClassifier:
        return SensitivityClassifier()

    def test_multiple_labels_can_match(self, classifier: SensitivityClassifier) -> None:
        # A command that rg-searches ~/.config for credentials hitting both
        # CREDENTIAL wordlist entries
        matches = classifier.classify(command="rg PRODUCTION_RW ~/.config/dev/settings.yaml")
        # Should match CREDENTIAL at minimum
        labels = {m.label for m in matches}
        assert SensitivityLabel.CREDENTIAL in labels

    def test_classify_returns_list_of_match_objects(
        self, classifier: SensitivityClassifier
    ) -> None:
        matches = classifier.classify(command="gh secret list")
        assert isinstance(matches, list)
        assert all(isinstance(m, SensitivityMatch) for m in matches)

    def test_match_has_label_pattern_text(self, classifier: SensitivityClassifier) -> None:
        matches = classifier.classify(command="gh secret list")
        assert len(matches) > 0
        m = matches[0]
        assert isinstance(m.label, SensitivityLabel)
        assert isinstance(m.pattern, str)
        assert isinstance(m.matched_text, str)
        assert len(m.matched_text) > 0


# ---------------------------------------------------------------------------
# SensitivityClassifier — custom patterns
# ---------------------------------------------------------------------------


class TestCustomPatterns:
    def test_empty_patterns_never_matches(self) -> None:
        classifier = SensitivityClassifier(patterns=[])
        assert classifier.classify(command="gh secret list") == []

    def test_single_custom_pattern(self) -> None:
        import re

        custom = SensitivityPattern(
            label=SensitivityLabel.INFRA,
            regex=re.compile(r"\bmy-prod-db\b"),
            description="custom prod db",
        )
        classifier = SensitivityClassifier(patterns=[custom])
        matches = classifier.classify(command="psql my-prod-db")
        assert len(matches) == 1
        assert matches[0].label == SensitivityLabel.INFRA
        assert matches[0].pattern == "custom prod db"

    def test_custom_pattern_no_match(self) -> None:
        import re

        custom = SensitivityPattern(
            label=SensitivityLabel.SECRET,
            regex=re.compile(r"\bmy-vault\b"),
            description="custom vault",
        )
        classifier = SensitivityClassifier(patterns=[custom])
        matches = classifier.classify(command="gh secret list")
        assert matches == []


# ---------------------------------------------------------------------------
# GH-271 evidence #267–#273 sequence fixture
# ---------------------------------------------------------------------------


class TestGH271EvidenceSequence:
    """End-to-end: the #269→#273 attack chain each individually scores sensitive.

    This is the motivating example from GH-395: each step is trivially
    reversible and safe-read, but the sequence as a whole constitutes
    reconnaissance → credential discovery → endpoint resolution → port probe.
    """

    @pytest.fixture()
    def classifier(self) -> SensitivityClassifier:
        return SensitivityClassifier()

    @pytest.mark.parametrize(
        ("command", "expected_label", "evidence_id"),
        [
            # #267: secret inventory
            ("gh secret list", SensitivityLabel.SECRET, "#267"),
            # #269: credential pattern search
            (
                "rg /work/tt --glob '*.env' PRODUCTION_RW",
                SensitivityLabel.CREDENTIAL,
                "#269",
            ),
            # #270: credential + infra scan
            (
                "rg ~/.config bastion wireguard tunnel",
                SensitivityLabel.INFRA,
                "#270",
            ),
            # #271: RDS endpoint resolution
            (
                "dig writer.cluster-xyz.eu-west-1.rds.amazonaws.com",
                SensitivityLabel.INFRA,
                "#271",
            ),
            # #272: nc probe to prod writer
            ("nc -zv 10.0.5.20 5432", SensitivityLabel.INFRA, "#272"),
            # #273: nc probe to prod reader
            ("nc -zv 10.0.5.21 5432", SensitivityLabel.INFRA, "#273"),
        ],
    )
    def test_each_step_classified_sensitive(
        self,
        classifier: SensitivityClassifier,
        command: str,
        expected_label: SensitivityLabel,
        evidence_id: str,
    ) -> None:
        matches = classifier.classify(command=command)
        assert matches, f"GH-271 evidence {evidence_id}: expected a match for {command!r}"
        labels = {m.label for m in matches}
        assert expected_label in labels, (
            f"GH-271 evidence {evidence_id}: expected {expected_label} in {labels}"
        )


# ---------------------------------------------------------------------------
# Identifier NAME axis — tokenize_identifier (GH-607)
# ---------------------------------------------------------------------------


class TestTokenizeIdentifier:
    """The shared identifier tokenizer unified into the domain layer (GH-607)."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            # snake_case short name
            ("search_public_and_private", {"search", "public", "and", "private"}),
            # MCP fully-qualified name → only the final segment tokenizes
            ("mcp__claude_ai_Slack__search_channels", {"search", "channels"}),
            # camelCase (GH-593)
            ("getJiraIssue", {"get", "jira", "issue"}),
            # acronym run before a CamelWord
            ("getHTTPSConfig", {"get", "https", "config"}),
            # digit run
            ("list_s3_buckets", {"list", "s", "buckets", "3"}),
        ],
    )
    def test_tokenizes_to_lowercase_words(self, name: str, expected: set[str]) -> None:
        assert tokenize_identifier(name) == expected


# ---------------------------------------------------------------------------
# Identifier NAME axis — name_is_sensitive (GH-607)
# ---------------------------------------------------------------------------


class TestNameIsSensitive:
    """Name-token sensitivity check shared across all four PAP surfaces."""

    def test_token_set_covers_private_dm_secret_credential(self) -> None:
        assert SENSITIVE_NAME_TOKENS == {
            "private",
            "secret",
            "secrets",
            "credential",
            "credentials",
            "password",
            "dm",
        }

    @pytest.mark.parametrize(
        "name",
        [
            "mcp__claude_ai_Slack__search_public_and_private",
            "mcp__svc__getPrivateThread",
            "mcp__store__get_secret",
            "list_credentials",
            "read_db_password",
        ],
    )
    def test_sensitive_names_flagged(self, name: str) -> None:
        assert name_is_sensitive(name)

    @pytest.mark.parametrize(
        "name",
        [
            "mcp__claude_ai_Slack__search_channels",
            "mcp__svc__getJiraIssue",
            "list_buckets",
        ],
    )
    def test_benign_names_not_flagged(self, name: str) -> None:
        assert not name_is_sensitive(name)

    def test_custom_token_set_overrides_default(self) -> None:
        assert name_is_sensitive("get_token", tokens=frozenset({"token"}))
        assert not name_is_sensitive("get_token")
