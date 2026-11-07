from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.commands.hook import hook
from dev10x.validators import reset_registry

_RUN = "dev10x.validators.review_stamp.subprocess_utils.run"
GH_PAYLOAD = json.dumps(
    {
        "headRefOid": "a" * 40,
        "headRefName": "feature",
        "url": "https://github.com/o/r/pull/7",
    }
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    friction = Dev10xConfigDir.friction_yaml()
    friction.parent.mkdir(parents=True, exist_ok=True)
    friction.write_text(
        yaml.safe_dump({"projects": [{"match": ["*/repo"], "review_stamp": "required"}]})
    )
    return repo


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV10X_HOOK_DISABLE", raising=False)
    reset_registry()


def _invoke(*, payload: dict[str, Any]) -> Any:
    def fake(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        stdout = GH_PAYLOAD if command[0] == "gh" else "t" * 40
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=stdout, stderr="")

    with patch(_RUN, side_effect=fake):
        return CliRunner().invoke(hook, ["validate-ship-gate"], input=json.dumps(payload))


def test_unstamped_merge_is_denied(checkout: Path) -> None:
    result = _invoke(
        payload={
            "tool_name": "mcp__plugin_dev10x_cli__merge_pr",
            "tool_input": {"pr_number": 7, "cwd": str(checkout)},
        }
    )

    assert result.exit_code == 2
    assert "DX019" in result.output


def test_other_tool_passes_silently(checkout: Path) -> None:
    result = _invoke(
        payload={
            "tool_name": "mcp__plugin_dev10x_cli__pr_get",
            "tool_input": {"number": 7, "cwd": str(checkout)},
        }
    )

    assert result.exit_code == 0
    assert result.output == ""


def test_disabled_rule_passes(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX019")
    reset_registry()

    result = _invoke(
        payload={
            "tool_name": "mcp__plugin_dev10x_cli__merge_pr",
            "tool_input": {"pr_number": 7, "cwd": str(checkout)},
        }
    )

    assert result.exit_code == 0
