"""Block records name the rule that produced them (GH-1095).

Before this, every audit record for a denied command was a bare
``outcome: block`` — you could count blocks but never attribute one to
a validator, so no frequency-by-class report was possible and no
friction fix could be shown to have worked.

The attribution travels: validator -> ValidatorChain (stamps rule_id)
-> emit() (hands it to the audit layer) -> audit_hook's finally (folds
it into the record). These tests pin each hop plus the end-to-end path.
"""

from __future__ import annotations

import pytest

from dev10x.domain.events.hook_input import HookAllow, HookAsk, HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.hooks import audit_emit
from dev10x.hooks.audit_emit import (
    audit_hook,
    clear_decision_attribution,
    set_audit_writer,
    set_decision_attribution,
)
from dev10x.hooks.hook_transport import emit
from dev10x.validators.registry import ValidatorChain, ValidatorRegistry


@pytest.fixture(autouse=True)
def reset_attribution() -> None:
    """The slot is module-level; tests share one process."""
    clear_decision_attribution()


class RecordingWriter:
    """Captures records instead of appending to the JSONL log."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    def audit_enabled(self) -> bool:
        return True

    def current_span_id(self) -> str:
        return "span-test"

    def new_span_id(self) -> str:
        return "span-test"

    def classify_outcome(self, *, exit_code: int) -> str:
        return "block" if exit_code == 2 else "ok"

    def append_record(self, *, record: dict) -> None:
        self.records.append(record)


@pytest.fixture
def writer() -> RecordingWriter:
    recorder = RecordingWriter()
    set_audit_writer(recorder)
    yield recorder
    set_audit_writer(None)


class StubValidator:
    """Minimal validator returning a fixed result."""

    def __init__(self, *, rule_id: str, result: object, profile: ProfileTier) -> None:
        self.rule_id = rule_id
        self.name = f"stub-{rule_id}"
        self.profile = profile
        self._result = result

    def should_run(self, *, inp: HookInput) -> bool:
        return True

    def validate(self, *, inp: HookInput) -> object:
        return self._result


class StubRegistry(ValidatorRegistry):
    def __init__(self, *, validators: list[object]) -> None:
        self._validators = validators

    def active(self) -> list[object]:
        return self._validators


def _chain_with(*, validator: object) -> ValidatorChain:
    return ValidatorChain(registry=StubRegistry(validators=[validator]))


def _run_chain(*, validator: object) -> object:
    inp = HookInput(tool_name="Bash", command="echo hi", raw={}, cwd="/tmp")
    return _chain_with(validator=validator).run(inp=inp)[0]


class TestChainStampsRuleId:
    def test_deny_gets_emitting_validators_rule_id(self) -> None:
        result = _run_chain(
            validator=StubValidator(
                rule_id="DX010",
                result=HookResult(message="blocked"),
                profile=ProfileTier.STANDARD,
            )
        )
        assert result.rule_id == "DX010"

    def test_ask_gets_emitting_validators_rule_id(self) -> None:
        result = _run_chain(
            validator=StubValidator(
                rule_id="DX014",
                result=HookAsk(message="sensitive", reason="infra probe"),
                profile=ProfileTier.STANDARD,
            )
        )
        assert result.rule_id == "DX014"

    def test_explicit_rule_id_is_not_overwritten(self) -> None:
        result = _run_chain(
            validator=StubValidator(
                rule_id="DX010",
                result=HookResult(message="blocked", rule_id="DX003"),
                profile=ProfileTier.STANDARD,
            )
        )
        assert result.rule_id == "DX003"

    def test_allow_passes_through_without_rule_id_field(self) -> None:
        result = _run_chain(
            validator=StubValidator(
                rule_id="DX010",
                result=HookAllow(message="fine"),
                profile=ProfileTier.STANDARD,
            )
        )
        assert not hasattr(result, "rule_id")

    def test_validator_without_a_rule_id_leaves_result_unstamped(self) -> None:
        result = _run_chain(
            validator=StubValidator(
                rule_id="",
                result=HookResult(message="blocked"),
                profile=ProfileTier.STANDARD,
            )
        )
        assert result.rule_id == ""


class TestSerialization:
    def test_deny_to_dict_includes_rule_id_when_set(self) -> None:
        assert HookResult(message="m", rule_id="DX010").to_dict()["rule_id"] == "DX010"

    def test_deny_to_dict_omits_rule_id_when_unset(self) -> None:
        assert "rule_id" not in HookResult(message="m").to_dict()

    def test_ask_to_dict_includes_rule_id_when_set(self) -> None:
        assert HookAsk(message="m", reason="r", rule_id="DX014").to_dict()["rule_id"] == "DX014"


class TestEmitRecordsAttribution:
    def test_deny_records_rule_id_and_reason(self) -> None:
        with pytest.raises(SystemExit):
            emit(HookResult(message="chain blocked", rule_id="DX010"))
        assert audit_emit._decision_attribution == {
            "rule_id": "DX010",
            "reason": "chain blocked",
        }

    def test_ask_records_reason_in_preference_to_message(self) -> None:
        with pytest.raises(SystemExit):
            emit(HookAsk(message="msg", reason="infra probe", rule_id="DX014"))
        assert audit_emit._decision_attribution["reason"] == "infra probe"

    def test_allow_records_nothing(self) -> None:
        with pytest.raises(SystemExit):
            emit(HookAllow(message="fine"))
        assert audit_emit._decision_attribution is None

    def test_deny_with_neither_rule_id_nor_message_records_nothing(self) -> None:
        with pytest.raises(SystemExit):
            emit(HookResult(message=""))
        assert audit_emit._decision_attribution is None


class TestReasonNormalization:
    def test_newlines_collapse_to_single_spaces(self) -> None:
        set_decision_attribution(rule_id="DX010", reason="line one\n\nline  two")
        assert audit_emit._decision_attribution["reason"] == "line one line two"

    def test_long_reason_is_truncated_with_ellipsis(self) -> None:
        set_decision_attribution(rule_id="DX010", reason="x" * 500)
        reason = audit_emit._decision_attribution["reason"]
        assert len(reason) == 200
        assert reason.endswith("…")


class TestAuditRecordCarriesAttribution:
    def test_block_record_names_the_rule(self, writer: RecordingWriter) -> None:
        @audit_hook(name="validate-bash", event="PreToolUse")
        def body() -> None:
            emit(HookResult(message="blocked by chain", rule_id="DX010"))

        with pytest.raises(SystemExit):
            body()

        record = writer.records[0]
        assert record["outcome"] == "block"
        assert record["rule_id"] == "DX010"
        assert record["reason"] == "blocked by chain"

    def test_attribution_does_not_leak_into_the_next_features_record(
        self, writer: RecordingWriter
    ) -> None:
        """The slot must not survive the record that consumed it.

        SessionStart/Stop orchestrators run several audit_hook-wrapped
        features in ONE process, catching each SystemExit and
        continuing — so a slot left set by feature A would be
        misattributed to feature B's record.
        """

        @audit_hook(name="feature-a", event="SessionStart")
        def feature_a() -> None:
            emit(HookResult(message="denied", rule_id="DX010"))

        @audit_hook(name="feature-b", event="SessionStart")
        def feature_b() -> None:
            return None

        with pytest.raises(SystemExit):
            feature_a()
        feature_b()

        assert writer.records[0]["rule_id"] == "DX010"
        assert "rule_id" not in writer.records[1]
        assert "reason" not in writer.records[1]

    def test_clean_exit_record_has_no_attribution_keys(self, writer: RecordingWriter) -> None:
        @audit_hook(name="validate-bash", event="PreToolUse")
        def body() -> None:
            return None

        body()

        record = writer.records[0]
        assert record["outcome"] == "ok"
        assert "rule_id" not in record
        assert "reason" not in record
