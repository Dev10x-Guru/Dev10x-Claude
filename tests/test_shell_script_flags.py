"""Syntax + flag-wiring checks for skill shell scripts (GH-311).

The repo behaviourally tests Python entry points only
(``test_script_loadability.py``); shell scripts are keyring/network
dependent and are validated at the syntax level here. These tests lock
in the GH-311 refactor that lets the jira and aws-vault scripts take
their config as a flag (avoiding the env-var-prefix invocation friction)
while keeping the env var as a fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SHELL_SCRIPTS = sorted(REPO_ROOT.glob("skills/**/scripts/*.sh"))


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_shell_script_syntax_is_valid(script: Path) -> None:
    result = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{script} failed bash -n: {result.stderr}"


def test_jira_env_accepts_tenant_flag() -> None:
    source = (REPO_ROOT / "skills" / "jira" / "scripts" / "_jira-env.sh").read_text()
    assert '"${1:-}" = "--tenant"' in source
    # Env var remains the fallback for one release.
    assert "JIRA_TENANT" in source


@pytest.mark.parametrize("name", ["secrets.sh", "kubectl.sh", "aws.sh"])
def test_aws_vault_scripts_accept_registry_flag(name: str) -> None:
    source = (REPO_ROOT / "skills" / "aws-vault" / "scripts" / name).read_text()
    assert '"${1:-}" == "--registry"' in source
    # Env var remains the fallback.
    assert "DEV10X_AWS_VAULT_REGISTRY" in source


def test_aws_wrapper_is_verb_aware_read_only() -> None:
    """GH-606 D6 / GH-605: aws.sh enforces a read allowlist + secret denylist.

    The credentialed `aws-vault exec` surface is verb-blind; this wrapper
    is the read-only gate, so a broad `:*` grant on it cannot run a
    mutating or secret-exfil AWS operation.
    """
    source = (REPO_ROOT / "skills" / "aws-vault" / "scripts" / "aws.sh").read_text()
    # Verb-aware allowlist marker (matched by update_paths' verb-blind check).
    assert "ALLOWED_PREFIXES=(" in source
    # Read prefixes pass; mutating ops fall through to deny.
    for prefix in ("describe-", "list-", "get-"):
        assert prefix in source
    # Secret-exfil reads are denied even though their verb is "get".
    assert "secretsmanager get-secret-value" in source
    assert "ssm get-parameter" in source
    assert "--with-decryption" in source
