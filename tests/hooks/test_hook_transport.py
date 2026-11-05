"""Tests for the hooks transport adapter (GH-511).

emit()/read_hook_input() own the Claude Code wire envelope and stdin
read that used to live on the domain value objects. HookRetry's
envelope is covered in test_permission_denied.py; the cwd-resolution
path is covered in test_cwd_discipline_sweep.py.
"""

from __future__ import annotations

import io
import json

import pytest
from dev10x.domain.events.hook_input import HookAllow, HookAsk, HookHint, HookResult
from dev10x.hooks.hook_transport import emit, read_hook_input, select_result


class TestEmitHookHint:
    """GH-1725: a hint reaches the agent as additionalContext and decides nothing."""

    @pytest.fixture()
    def emitted(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
        with pytest.raises(SystemExit) as exc_info:
            emit(HookHint(message="move the flags"))
        captured = capsys.readouterr()
        return exc_info.value.code, captured.out, captured.err

    def test_exits_with_code_0(self, emitted: tuple[int, str, str]) -> None:
        assert emitted[0] == 0

    def test_writes_additional_context_to_stdout(self, emitted: tuple[int, str, str]) -> None:
        output = json.loads(emitted[1])

        assert output == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "move the flags",
            }
        }

    def test_writes_nothing_to_stderr(self, emitted: tuple[int, str, str]) -> None:
        assert emitted[2] == ""


class TestSelectResult:
    def test_none_when_nothing_spoke(self) -> None:
        assert select_result([]) is None

    def test_a_decision_after_a_hint_still_wins(self) -> None:
        deny = HookResult(message="no", rule_id="DX004")

        assert select_result([HookHint(message="tip"), deny]) == deny

    def test_a_later_deny_beats_an_earlier_ask(self) -> None:
        """GH-1795: precedence is deny > ask > allow, not chain order."""
        deny = HookResult(message="no")

        assert select_result([HookAsk(message="ask"), deny]) == deny

    def test_a_later_deny_beats_an_earlier_allow(self) -> None:
        deny = HookResult(message="no", rule_id="DX003")

        assert select_result([HookAllow(message="ok", decides=True), deny]) == deny

    def test_a_later_ask_beats_an_earlier_allow(self) -> None:
        ask = HookAsk(message="sensitive", rule_id="DX014")

        assert select_result([HookAllow(message="ok", decides=True), ask]) == ask

    def test_first_of_a_kind_keeps_chain_order(self) -> None:
        first = HookResult(message="first")

        assert select_result([first, HookResult(message="second")]) == first

    def test_a_deciding_allow_carries_the_hints(self) -> None:
        selected = select_result(
            [
                HookHint(message="tip", rule_id="DX006"),
                HookAllow(message="ok", decides=True, rule_id="DX011"),
                HookAllow(message="note"),
            ]
        )

        assert selected == HookAllow(message="ok\n\ntip\n\nnote", decides=True, rule_id="DX011")

    def test_an_advisory_allow_counts_as_a_hint(self) -> None:
        selected = select_result([HookAllow(rule_id="DX001"), HookAllow(message="m", rule_id="X")])

        assert selected == HookHint(message="m", rule_id="X")

    def test_messageless_advisory_allows_emit_nothing(self) -> None:
        assert select_result([HookAllow(), HookAllow()]) is None

    def test_hints_alone_merge_into_one(self) -> None:
        merged = select_result(
            [HookHint(message="a", rule_id="DX006"), HookHint(message="b", rule_id="DX099")]
        )

        assert merged == HookHint(message="a\n\nb", rule_id="DX006")


class TestEmitHookResult:
    def test_exits_with_code_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            emit(HookResult(message="blocked"))
        assert exc_info.value.code == 2

    def test_writes_deny_envelope(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            emit(HookResult(message="blocked"))
        output = json.loads(capsys.readouterr().err)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert output["systemMessage"] == "blocked"


class TestEmitDecidingHookAllow:
    """GH-1795: a rule-backed allow skips the permission prompt."""

    def test_writes_the_allow_envelope_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            emit(HookAllow(message="every segment allowed", decides=True))
        captured = capsys.readouterr()

        assert exc_info.value.code == 0
        assert json.loads(captured.out) == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "every segment allowed",
                "additionalContext": "every segment allowed",
            }
        }
        assert captured.err == ""

    def test_needs_no_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            emit(HookAllow(decides=True))

        assert json.loads(capsys.readouterr().out) == {
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
        }


class TestEmitHookAllow:
    """GH-1775: an advisory allow decides nothing."""

    def test_exits_with_code_0(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            emit(HookAllow())
        assert exc_info.value.code == 0

    def test_message_reaches_the_agent_without_a_decision(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            emit(HookAllow(message="prefer the wrapper"))
        captured = capsys.readouterr()

        assert json.loads(captured.out) == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "prefer the wrapper",
            }
        }
        assert captured.err == ""

    def test_writes_nothing_without_a_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            emit(HookAllow())
        captured = capsys.readouterr()

        assert (captured.out, captured.err) == ("", "")


class TestEmitHookAsk:
    def test_exits_with_code_0(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            emit(HookAsk(message="sensitive", reason="why"))
        assert exc_info.value.code == 0

    def test_writes_nothing_to_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """GH-1775: Claude Code never reads an exit-0 hook's stderr."""
        with pytest.raises(SystemExit):
            emit(HookAsk(message="sensitive", reason="why"))
        assert capsys.readouterr().err == ""

    def test_writes_ask_envelope(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            emit(HookAsk(message="sensitive probe", reason="DX014 INFRA target"))
        output = json.loads(capsys.readouterr().out)
        hook_output = output["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "PreToolUse"
        assert hook_output["permissionDecision"] == "ask"
        assert hook_output["permissionDecisionReason"] == "DX014 INFRA target"
        assert output["systemMessage"] == "sensitive probe"

    def test_reason_falls_back_to_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            emit(HookAsk(message="only a message"))
        output = json.loads(capsys.readouterr().out)
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "only a message"

    def test_omits_system_message_when_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            emit(HookAsk(reason="reason only"))
        output = json.loads(capsys.readouterr().out)
        assert "systemMessage" not in output


class TestReadHookInput:
    def test_parses_tool_name_and_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        inp = read_hook_input()
        assert inp.tool_name == "Bash"
        assert inp.command == "git status"

    def test_empty_stdin_yields_blank_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        inp = read_hook_input()
        assert inp.tool_name == ""
        assert inp.command == ""
