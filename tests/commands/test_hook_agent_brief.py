from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.commands.hook import hook
from dev10x.validators import reset_registry


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV10X_HOOK_DISABLE", raising=False)
    reset_registry()


def _invoke(*, payload: dict[str, Any]) -> Any:
    return CliRunner().invoke(hook, ["validate-agent-brief"], input=json.dumps(payload))


def test_unnamed_skill_emits_context_without_a_decision() -> None:
    result = _invoke(
        payload={"tool_name": "Agent", "tool_input": {"prompt": "Write a Playwright harness."}}
    )

    output = json.loads(result.output)["hookSpecificOutput"]
    assert result.exit_code == 0
    assert output["hookEventName"] == "PreToolUse"
    assert "DX020" in output["additionalContext"]
    assert "permissionDecision" not in output


def test_deny_mode_blocks_the_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    friction = Dev10xConfigDir.friction_yaml()
    friction.parent.mkdir(parents=True, exist_ok=True)
    friction.write_text(
        yaml.safe_dump({"projects": [{"match": ["*/repo"], "dx020": {"mode": "deny"}}]})
    )
    monkeypatch.chdir(repo)

    result = _invoke(payload={"tool_name": "Agent", "tool_input": {"prompt": "git push it"}})

    assert result.exit_code == 2
    assert "DX020" in result.output


def test_named_skill_passes_silently() -> None:
    result = _invoke(
        payload={
            "tool_name": "Agent",
            "tool_input": {"prompt": "Run Skill(dev10x-qa:qa-self) for the Playwright flow."},
        }
    )

    assert result.exit_code == 0
    assert result.output == ""


def test_disabled_rule_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV10X_HOOK_DISABLE", "DX020")
    reset_registry()

    result = _invoke(payload={"tool_name": "Agent", "tool_input": {"prompt": "git push it"}})

    assert result.exit_code == 0
    assert result.output == ""
