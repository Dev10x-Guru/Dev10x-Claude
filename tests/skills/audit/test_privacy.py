"""Tests for the privacy / external-service audit scanner (GH-6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.audit import privacy


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


# ─────────────────────────────────────────────────────────────────────
# Service detection
# ─────────────────────────────────────────────────────────────────────


class TestServiceDetection:
    @pytest.mark.parametrize(
        ("service", "snippet"),
        [
            ("GitHub", "subprocess.run(['gh', 'pr', 'view', '42'])"),
            ("GitHub", "result = run('gh api repos/foo/bar')"),
            ("Linear", "see https://linear.app/foo/issue/BAR-1"),
            ("Linear", "tool = 'mcp__claude_ai_Linear__list_issues'"),
            ("JIRA", "url = 'https://example.atlassian.net/browse/X-1'"),
            ("Slack", "post to slack.com webhook"),
            ("Slack", "mcp__claude_ai_Slack__send_message"),
            ("Sentry", "mcp__sentry__get_issue_details"),
            ("Sentry", "fetch('sentry.io/api/0/issues/123')"),
            ("AWS Secrets Manager", "aws-vault exec prod -- env"),
            ("AWS Secrets Manager", "aws secretsmanager get-secret-value"),
            ("Anthropic API", "anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}"),
            ("Anthropic API", "uses: anthropics/claude-code-action@v1"),
            ("PyPI", "twine upload dist/*"),
            ("Kubernetes API", "kubectl get pods -n prod"),
            ("Postgres", "psql -h db.example.com -U app"),
        ],
    )
    def test_service_pattern_fires(self, tmp_path: Path, service: str, snippet: str) -> None:
        path = _write(tmp_path / "sample.md", snippet + "\n")
        usages, _ = privacy.scan_paths([path])
        assert any(u.service == service for u in usages), (
            f"Expected {service} in {[u.service for u in usages]}"
        )

    @pytest.mark.parametrize(
        "snippet",
        [
            "this references the github actions runtime via name only",
            "the linear regression test predicts foo",
            "merging is tricky when the slack channel is busy",
            "the psqlite library is unrelated",
            "gh.copy() is a method, not the gh CLI",
        ],
    )
    def test_negative_lookups_do_not_fire(self, tmp_path: Path, snippet: str) -> None:
        path = _write(tmp_path / "sample.md", snippet + "\n")
        usages, _ = privacy.scan_paths([path])
        assert usages == []

    def test_inline_suppression_silences_service(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path / "sample.py",
            "# privacy-audit: allow Kubernetes API — example doc only\n"
            "kubectl_invocation = 'kubectl get pods'  "
            "# privacy-audit: allow Kubernetes API — see line above\n",
        )
        usages, _ = privacy.scan_paths([path])
        assert [u.service for u in usages] == []


# ─────────────────────────────────────────────────────────────────────
# Outbound-network imports
# ─────────────────────────────────────────────────────────────────────


class TestNetImports:
    @pytest.mark.parametrize(
        "snippet",
        [
            "import requests",
            "import httpx",
            "from urllib.request import urlopen",
            "import aiohttp",
        ],
    )
    def test_flags_outbound_imports_in_source(self, tmp_path: Path, snippet: str) -> None:
        path = _write(tmp_path / "src" / "module.py", snippet + "\n")
        _, net = privacy.scan_paths([path])
        assert len(net) == 1
        assert net[0].path == path

    def test_does_not_flag_imports_in_tests(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "tests" / "test_x.py", "import requests\n")
        _, net = privacy.scan_paths([path])
        assert net == []

    def test_does_not_flag_imports_in_privacy_policy(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "PRIVACY_POLICY.md", "import requests\n")
        _, net = privacy.scan_paths([path])
        assert net == []

    @pytest.mark.parametrize(
        "module",
        [
            "src/dev10x/skills/notifications/gchat_notify.py",
            "src/dev10x/skills/notifications/slack_notify.py",
        ],
    )
    def test_documented_notification_transports_are_exempt(
        self,
        tmp_path: Path,
        module: str,
    ) -> None:
        """User-invoked notification transports may reach the network (GH-917).

        Both post messages the user approved to a service documented in
        PRIVACY_POLICY.md. Dropping the exemption would force the Slack
        transport back onto a hard `slack_sdk` dependency.
        """
        path = _write(tmp_path / module, "import urllib.request\n")
        _, net = privacy.scan_paths([path])
        assert net == []

    def test_slack_transport_service_is_documented_in_policy(self) -> None:
        """The exemption is only legitimate while the policy names Slack."""
        policy = Path(__file__).parents[3] / "PRIVACY_POLICY.md"
        assert "Slack" in privacy.parse_documented_services(policy.read_text())


# ─────────────────────────────────────────────────────────────────────
# Privacy policy parsing
# ─────────────────────────────────────────────────────────────────────


class TestPolicyParser:
    def test_extracts_documented_services(self) -> None:
        policy = """
# Privacy Policy

## Third-party integrations

| Integration | Credentials | Data exchanged |
|-------------|-------------|----------------|
| GitHub (`gh` CLI, MCP) | Your GitHub token | PR payloads |
| Linear (MCP) | Your Linear OAuth session | Issues |
| JIRA (`Dev10x:jira`) | API token | Issues |

## Children
"""
        documented = privacy.parse_documented_services(policy)
        assert documented == frozenset({"GitHub", "Linear", "JIRA"})

    def test_returns_empty_on_missing_table(self) -> None:
        assert privacy.parse_documented_services("") == frozenset()
        assert privacy.parse_documented_services("# Privacy\nNo table here.") == frozenset()


# ─────────────────────────────────────────────────────────────────────
# End-to-end audit
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def policy_with(tmp_path: Path):
    """Factory that writes a privacy policy listing the given services."""

    def factory(services: list[str]) -> Path:
        rows = "\n".join(f"| {svc} | token | data |" for svc in services)
        body = (
            "# Privacy Policy\n\n"
            "## Third-party integrations\n\n"
            "| Integration | Credentials | Data exchanged |\n"
            "|-------------|-------------|----------------|\n"
            f"{rows}\n"
        )
        return _write(tmp_path / "PRIVACY_POLICY.md", body)

    return factory


class TestAudit:
    def test_documented_service_passes(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with(["GitHub"])
        source = _write(tmp_path / "src" / "x.py", "subprocess.run(['gh', 'pr', 'view'])\n")
        result = privacy.audit(scan_paths_=[source], policy_path=policy)
        assert result.undocumented == frozenset()
        assert result.has_violations is False

    def test_undocumented_service_flags_violation(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with(["GitHub"])
        source = _write(tmp_path / "src" / "x.py", "kubectl_call = 'kubectl get pods'\n")
        result = privacy.audit(scan_paths_=[source], policy_path=policy)
        assert "Kubernetes API" in result.undocumented
        assert result.has_violations is True

    def test_outbound_import_flags_violation_even_when_service_documented(
        self, tmp_path: Path, policy_with
    ) -> None:
        policy = policy_with(["GitHub"])
        source = _write(tmp_path / "src" / "x.py", "import requests\n")
        result = privacy.audit(scan_paths_=[source], policy_path=policy)
        assert len(result.net_imports) == 1
        assert result.has_violations is True

    def test_missing_policy_treated_as_empty(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "src" / "x.py", "kubectl_call = 'kubectl'\n")
        result = privacy.audit(scan_paths_=[source], policy_path=tmp_path / "missing.md")
        assert "Kubernetes API" in result.undocumented


class TestFormatMethods:
    def test_service_usage_format(self) -> None:
        usage = privacy.ServiceUsage(
            service="GitHub",
            kind="cli",
            path=Path("src/x.py"),
            line_number=10,
            snippet="  gh pr view 1  ",
        )
        assert usage.format() == "src/x.py:10: [GitHub/cli] gh pr view 1"

    def test_net_violation_format(self) -> None:
        violation = privacy.NetImportViolation(
            module="requests",
            path=Path("src/x.py"),
            line_number=3,
            snippet="import requests",
        )
        formatted = violation.format()
        assert "src/x.py:3" in formatted
        assert "requests" in formatted
        assert "outbound-network" in formatted


class TestFileIteration:
    def test_single_file_path_yielded_directly(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with(["GitHub"])
        f = _write(tmp_path / "a.py", "subprocess.run(['gh', 'pr', 'view'])\n")
        result = privacy.audit(scan_paths_=[f], policy_path=policy)
        assert any(u.service == "GitHub" for u in result.usages)

    def test_missing_path_silently_skipped(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with([])
        result = privacy.audit(scan_paths_=[tmp_path / "does-not-exist"], policy_path=policy)
        assert result.usages == ()
        assert result.net_imports == ()

    def test_skipped_dirs_are_excluded(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with([])
        _write(
            tmp_path / "node_modules" / "dep" / "x.py",
            "kubectl_call = 'kubectl'\n",
        )
        result = privacy.audit(scan_paths_=[tmp_path], policy_path=policy)
        assert result.usages == ()

    def test_unscanned_extensions_are_excluded(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with([])
        _write(tmp_path / "blob.bin", "kubectl content\n")
        result = privacy.audit(scan_paths_=[tmp_path], policy_path=policy)
        assert result.usages == ()


class TestPolicyParserSeparatorRow:
    def test_skips_separator_row(self) -> None:
        policy = """
| Integration | Credentials | Data |
| ----------- | ----------- | ---- |
| GitHub | token | data |
"""
        documented = privacy.parse_documented_services(policy)
        assert documented == frozenset({"GitHub"})

    def test_skips_malformed_table_row(self) -> None:
        policy = """
| Integration | Credentials | Data |
| GitHub
| Linear | token | data |
"""
        documented = privacy.parse_documented_services(policy)
        assert documented == frozenset({"Linear"})


class TestUnreadableFile:
    def test_unreadable_file_silently_skipped(self, tmp_path: Path, policy_with) -> None:
        import os

        policy = policy_with([])
        path = _write(tmp_path / "src" / "x.py", "kubectl_call = 'kubectl'\n")
        os.chmod(path, 0o000)
        try:
            result = privacy.audit(scan_paths_=[path], policy_path=policy)
        finally:
            os.chmod(path, 0o644)
        assert result.usages == ()


class TestInventoryRendering:
    def test_renders_grouped_markdown(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with(["GitHub"])
        source = _write(
            tmp_path / "src" / "x.py",
            "subprocess.run(['gh', 'pr', 'view'])\nkubectl_call = 'kubectl get pods'\n",
        )
        result = privacy.audit(scan_paths_=[source], policy_path=policy)
        rendered = privacy.render_inventory_markdown(result)
        assert "## GitHub (documented: yes)" in rendered
        assert "## Kubernetes API (documented: **NO**)" in rendered

    def test_renders_truncates_long_lists(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with([])
        body = "\n".join("kubectl_call = 'kubectl'" for _ in range(25)) + "\n"
        source = _write(tmp_path / "src" / "x.py", body)
        result = privacy.audit(scan_paths_=[source], policy_path=policy)
        rendered = privacy.render_inventory_markdown(result)
        assert "and 5 more" in rendered

    def test_empty_inventory_message(self, tmp_path: Path, policy_with) -> None:
        policy = policy_with([])
        empty = _write(tmp_path / "src" / "x.py", "x = 1\n")
        result = privacy.audit(scan_paths_=[empty], policy_path=policy)
        rendered = privacy.render_inventory_markdown(result)
        assert "No external services detected" in rendered
