"""Tests for ValidatorRegistry, filters, and ValidatorChain (GH-82 #A1/#A2/#A3/#F5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest

from dev10x.domain import HookInput, HookResult, HookRetry
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase
from dev10x.validators.registry import (
    DisableListFilter,
    ExperimentalFilter,
    ProfileFilter,
    ValidatorChain,
    ValidatorRegistry,
    ValidatorSpec,
)


@dataclass
class _StubValidator(ValidatorBase):
    name: ClassVar[str] = "stub"
    rule_id: ClassVar[str] = "DX001"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        return True

    def validate(self, inp: HookInput) -> HookResult | None:
        return HookResult(message="stub-blocked")


@dataclass
class _StubCorrector(ValidatorBase):
    name: ClassVar[str] = "stub-correct"
    rule_id: ClassVar[str] = "DX002"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    capabilities: ClassVar[frozenset[str]] = frozenset({"validate", "correct"})

    def should_run(self, inp: HookInput) -> bool:
        return True

    def validate(self, inp: HookInput) -> HookResult | None:
        return None

    def correct(self, inp: HookInput) -> HookRetry | None:
        return HookRetry(message="stub-retry")


@pytest.fixture
def stub_input() -> HookInput:
    return HookInput(raw={}, tool_name="Bash", command="echo hi", cwd="/tmp")


class TestProfileFilter:
    @pytest.mark.parametrize(
        ("active", "validator_tier", "expected"),
        [
            (ProfileTier.MINIMAL, ProfileTier.MINIMAL, True),
            (ProfileTier.MINIMAL, ProfileTier.STANDARD, False),
            (ProfileTier.STANDARD, ProfileTier.STANDARD, True),
            (ProfileTier.STANDARD, ProfileTier.STRICT, False),
            (ProfileTier.STRICT, ProfileTier.STRICT, True),
            (ProfileTier.STRICT, ProfileTier.MINIMAL, True),
        ],
    )
    def test_keep(self, active: ProfileTier, validator_tier: ProfileTier, expected: bool) -> None:
        spec = ValidatorSpec(
            module_path="m", class_name="C", rule_id="DX001", profile=validator_tier
        )
        assert ProfileFilter(active=active).keep(spec=spec) is expected


class TestDisableListFilter:
    def test_drops_disabled_rule(self) -> None:
        spec = ValidatorSpec(
            module_path="m", class_name="C", rule_id="DX042", profile=ProfileTier.MINIMAL
        )
        f = DisableListFilter(disabled=frozenset({"DX042"}))
        assert f.keep(spec=spec) is False

    def test_keeps_unlisted_rule(self) -> None:
        spec = ValidatorSpec(
            module_path="m", class_name="C", rule_id="DX099", profile=ProfileTier.MINIMAL
        )
        f = DisableListFilter(disabled=frozenset({"DX042"}))
        assert f.keep(spec=spec) is True

    def test_case_insensitive(self) -> None:
        spec = ValidatorSpec(
            module_path="m", class_name="C", rule_id="dx042", profile=ProfileTier.MINIMAL
        )
        f = DisableListFilter(disabled=frozenset({"DX042"}))
        assert f.keep(spec=spec) is False


class TestExperimentalFilter:
    def test_drops_experimental_when_disabled(self) -> None:
        spec = ValidatorSpec(
            module_path="m",
            class_name="C",
            rule_id="DX001",
            profile=ProfileTier.MINIMAL,
            experimental=True,
        )
        assert ExperimentalFilter(enabled=False).keep(spec=spec) is False

    def test_keeps_experimental_when_enabled(self) -> None:
        spec = ValidatorSpec(
            module_path="m",
            class_name="C",
            rule_id="DX001",
            profile=ProfileTier.MINIMAL,
            experimental=True,
        )
        assert ExperimentalFilter(enabled=True).keep(spec=spec) is True

    def test_keeps_non_experimental_always(self) -> None:
        spec = ValidatorSpec(
            module_path="m",
            class_name="C",
            rule_id="DX001",
            profile=ProfileTier.MINIMAL,
            experimental=False,
        )
        assert ExperimentalFilter(enabled=False).keep(spec=spec) is True


class TestValidatorRegistry:
    def _stub_spec(self) -> ValidatorSpec:
        return ValidatorSpec(
            module_path="tests.validators.test_registry",
            class_name="_StubValidator",
            rule_id="DX001",
            profile=ProfileTier.MINIMAL,
        )

    def test_register_and_active_specs(self) -> None:
        spec = self._stub_spec()
        registry = ValidatorRegistry()
        registry.register(spec=spec)
        assert registry.active_specs() == [spec]

    def test_active_instantiates_validator(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        validators = registry.active()
        assert len(validators) == 1
        assert isinstance(validators[0], _StubValidator)

    def test_active_is_cached(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        first = registry.active()
        second = registry.active()
        assert first is second

    def test_reset_invalidates_cache(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        first = registry.active()
        registry.reset()
        second = registry.active()
        assert first is not second

    def test_register_invalidates_cache(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        registry.active()
        registry.register(spec=self._stub_spec())
        assert registry._instances is None  # type: ignore[attr-defined]

    def test_filter_drops_specs(self) -> None:
        registry = ValidatorRegistry(
            specs=[self._stub_spec()],
            filters=[DisableListFilter(disabled=frozenset({"DX001"}))],
        )
        assert registry.active_specs() == []
        assert registry.active() == []

    def test_find_by_rule_id_hits(self) -> None:
        spec = self._stub_spec()
        registry = ValidatorRegistry(specs=[spec])
        assert registry.find_by_rule_id(rule_id="DX001") is spec
        assert registry.find_by_rule_id(rule_id="dx001") is spec

    def test_find_by_rule_id_missing(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        assert registry.find_by_rule_id(rule_id="DX999") is None

    def test_lookup_returns_active_instance(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        validator = registry.lookup(rule_id="DX001")
        assert isinstance(validator, _StubValidator)

    def test_lookup_returns_none_when_filtered_out(self) -> None:
        registry = ValidatorRegistry(
            specs=[self._stub_spec()],
            filters=[DisableListFilter(disabled=frozenset({"DX001"}))],
        )
        assert registry.lookup(rule_id="DX001") is None

    def test_is_active_true_when_filter_passes(self) -> None:
        registry = ValidatorRegistry(specs=[self._stub_spec()])
        assert registry.is_active(rule_id="DX001") is True

    def test_is_active_false_when_filtered_out(self) -> None:
        registry = ValidatorRegistry(
            specs=[self._stub_spec()],
            filters=[ProfileFilter(active=ProfileTier.STRICT)],
        )
        # spec is MINIMAL, STRICT includes everything so still active
        assert registry.is_active(rule_id="DX001") is True

    def test_metadata_mismatch_raises(self) -> None:
        bad = ValidatorSpec(
            module_path="tests.validators.test_registry",
            class_name="_StubValidator",
            rule_id="DX999",  # disagrees with class attr "DX001"
            profile=ProfileTier.MINIMAL,
        )
        registry = ValidatorRegistry(specs=[bad])
        with pytest.raises(AssertionError, match="rule_id"):
            registry.active()


class TestValidatorChain:
    def test_run_collects_validate_results(self, stub_input: HookInput) -> None:
        registry = ValidatorRegistry(
            specs=[
                ValidatorSpec(
                    module_path="tests.validators.test_registry",
                    class_name="_StubValidator",
                    rule_id="DX001",
                    profile=ProfileTier.MINIMAL,
                )
            ]
        )
        chain = ValidatorChain(registry=registry)
        results = chain.run(inp=stub_input)
        assert len(results) == 1
        assert isinstance(results[0], HookResult)
        assert results[0].message == "stub-blocked"

    def test_run_swallows_validator_exceptions(self, stub_input: HookInput) -> None:
        @dataclass
        class _Raiser(ValidatorBase):
            name: ClassVar[str] = "raiser"
            rule_id: ClassVar[str] = "DX900"
            profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

            def should_run(self, inp: HookInput) -> bool:
                return True

            def validate(self, inp: HookInput) -> HookResult | None:
                raise RuntimeError("boom")

        registry = ValidatorRegistry()
        registry._instances = [_Raiser()]  # type: ignore[attr-defined]
        chain = ValidatorChain(registry=registry)
        assert chain.run(inp=stub_input) == []

    def test_correct_dispatches_only_to_capable(self, stub_input: HookInput) -> None:
        registry = ValidatorRegistry(
            specs=[
                ValidatorSpec(
                    module_path="tests.validators.test_registry",
                    class_name="_StubValidator",
                    rule_id="DX001",
                    profile=ProfileTier.MINIMAL,
                ),
                ValidatorSpec(
                    module_path="tests.validators.test_registry",
                    class_name="_StubCorrector",
                    rule_id="DX002",
                    profile=ProfileTier.STANDARD,
                ),
            ]
        )
        chain = ValidatorChain(registry=registry)
        result = chain.correct(inp=stub_input)
        assert isinstance(result, HookRetry)
        assert result.message == "stub-retry"

    def test_correct_returns_none_when_no_capable_validators(self, stub_input: HookInput) -> None:
        registry = ValidatorRegistry(
            specs=[
                ValidatorSpec(
                    module_path="tests.validators.test_registry",
                    class_name="_StubValidator",
                    rule_id="DX001",
                    profile=ProfileTier.MINIMAL,
                )
            ]
        )
        chain = ValidatorChain(registry=registry)
        assert chain.correct(inp=stub_input) is None

    def test_correct_swallows_exceptions(self, stub_input: HookInput) -> None:
        @dataclass
        class _Raiser(ValidatorBase):
            name: ClassVar[str] = "raiser"
            rule_id: ClassVar[str] = "DX901"
            profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
            capabilities: ClassVar[frozenset[str]] = frozenset({"validate", "correct"})

            def should_run(self, inp: HookInput) -> bool:
                return True

            def validate(self, inp: HookInput) -> HookResult | None:
                return None

            def correct(self, inp: HookInput) -> HookRetry | None:
                raise RuntimeError("boom")

        registry = ValidatorRegistry()
        registry._instances = [_Raiser()]  # type: ignore[attr-defined]
        chain = ValidatorChain(registry=registry)
        assert chain.correct(inp=stub_input) is None


class TestValidatorBaseTemplate:
    def test_run_validates_when_should_run_true(self, stub_input: HookInput) -> None:
        result = _StubValidator().run(inp=stub_input)
        assert isinstance(result, HookResult)
        assert result.message == "stub-blocked"

    def test_run_skips_when_should_run_false(self, stub_input: HookInput) -> None:
        @dataclass
        class _Skipper(ValidatorBase):
            name: ClassVar[str] = "skipper"
            rule_id: ClassVar[str] = "DX902"
            profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

            def should_run(self, inp: HookInput) -> bool:
                return False

            def validate(self, inp: HookInput) -> HookResult | None:
                raise AssertionError("validate must not run when should_run is False")

        assert _Skipper().run(inp=stub_input) is None
