"""Tests for HookInput and HookResult DTOs."""

from __future__ import annotations

import pytest

from dev10x.domain import HookAllow, HookAsk, HookInput, HookResult


class TestHookInputFromDict:
    @pytest.fixture()
    def hook_input(self) -> HookInput:
        return HookInput.from_dict(
            data={
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            }
        )

    def test_tool_name(self, hook_input: HookInput) -> None:
        assert hook_input.tool_name == "Bash"

    def test_command(self, hook_input: HookInput) -> None:
        assert hook_input.command == "git status"

    def test_raw_preserved(self, hook_input: HookInput) -> None:
        assert hook_input.raw["tool_name"] == "Bash"


class TestHookInputFromEmptyDict:
    @pytest.fixture()
    def hook_input(self) -> HookInput:
        return HookInput.from_dict(data={})

    def test_tool_name_empty(self, hook_input: HookInput) -> None:
        assert hook_input.tool_name == ""

    def test_command_empty(self, hook_input: HookInput) -> None:
        assert hook_input.command == ""


class TestHookResult:
    def test_to_dict_decision_deny(self) -> None:
        assert HookResult(message="blocked").to_dict()["decision"] == "deny"

    def test_to_dict_message(self) -> None:
        assert HookResult(message="blocked").to_dict()["message"] == "blocked"


class TestHookAllow:
    def test_to_dict_decision_allow(self) -> None:
        assert HookAllow().to_dict()["decision"] == "allow"

    def test_to_dict_message_defaults_empty(self) -> None:
        assert HookAllow().to_dict()["message"] == ""

    def test_to_dict_message_preserved(self) -> None:
        assert HookAllow(message="auto-approved").to_dict()["message"] == "auto-approved"


class TestHookAsk:
    def test_to_dict_decision_ask(self) -> None:
        assert HookAsk().to_dict()["decision"] == "ask"

    def test_to_dict_message_and_reason_default_empty(self) -> None:
        result = HookAsk().to_dict()
        assert result["message"] == ""
        assert result["reason"] == ""

    def test_to_dict_preserves_message_and_reason(self) -> None:
        result = HookAsk(message="sensitive", reason="DX014 INFRA target").to_dict()
        assert result["message"] == "sensitive"
        assert result["reason"] == "DX014 INFRA target"
