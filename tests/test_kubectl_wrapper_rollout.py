"""Behavioural checks for the read-only kubectl wrapper's rollout gate (GH-1821).

``rollout status`` / ``rollout history`` only read, so the wrapper passes
them; every other ``rollout`` sub-verb mutates and stays denied. ``yq`` and
``aws-vault`` are stubbed on PATH, so no cluster is ever contacted.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
KUBECTL_SH = REPO_ROOT / "plugins" / "infra" / "skills" / "aws-vault" / "scripts" / "kubectl.sh"

YQ_STUB = """#!/usr/bin/env bash
case "$1" in
    *aws_vault_profile*) echo stub-profile ;;
    *k8s.context*) echo stub-context ;;
    *k8s.namespace*) echo stub-namespace ;;
esac
"""

AWS_VAULT_STUB = """#!/usr/bin/env bash
echo "AWS_VAULT_CALLED $*"
"""


def _write_executable(*, path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


@pytest.fixture
def stub_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(path=bin_dir / "yq", content=YQ_STUB)
    _write_executable(path=bin_dir / "aws-vault", content=AWS_VAULT_STUB)
    registry = tmp_path / "registry.yaml"
    registry.write_text("environments: {}\n")
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DEV10X_AWS_VAULT_REGISTRY": str(registry),
    }


def _run_wrapper(*, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(KUBECTL_SH), "staging", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["rollout", "status", "deploy/web", "--timeout=15s"],
        ["rollout", "history", "deploy/web"],
    ],
)
def test_read_only_rollout_subverbs_reach_kubectl(
    stub_env: dict[str, str],
    args: list[str],
) -> None:
    result = _run_wrapper(args=args, env=stub_env)

    assert result.returncode == 0
    assert "AWS_VAULT_CALLED exec stub-profile -- kubectl --context stub-context" in result.stdout
    assert " ".join(args) in result.stdout


@pytest.mark.parametrize(
    "subverb",
    ["undo", "restart", "pause", "resume", "frobnicate"],
)
def test_mutating_or_unknown_rollout_subverbs_are_denied(
    stub_env: dict[str, str],
    subverb: str,
) -> None:
    result = _run_wrapper(args=["rollout", subverb, "deploy/web"], env=stub_env)

    assert result.returncode == 1
    assert "AWS_VAULT_CALLED" not in result.stdout
    assert f"verb 'rollout {subverb}' is not permitted" in result.stderr
    assert "aws-vault exec stub-profile" in result.stderr


def test_rollout_without_a_subverb_is_denied(stub_env: dict[str, str]) -> None:
    result = _run_wrapper(args=["rollout"], env=stub_env)

    assert result.returncode == 1
    assert "AWS_VAULT_CALLED" not in result.stdout


def test_denied_flags_still_apply_to_allowed_rollout(stub_env: dict[str, str]) -> None:
    result = _run_wrapper(
        args=["rollout", "status", "deploy/web", "--as=admin"],
        env=stub_env,
    )

    assert result.returncode == 1
    assert "AWS_VAULT_CALLED" not in result.stdout
    assert "flag '--as=admin' is not permitted" in result.stderr


def test_other_mutating_verbs_remain_denied(stub_env: dict[str, str]) -> None:
    result = _run_wrapper(args=["delete", "pod/web"], env=stub_env)

    assert result.returncode == 1
    assert "verb 'delete' is not permitted" in result.stderr
