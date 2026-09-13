"""The retired-path session.yaml is reported, not silently tolerated (GH-1259).

ADR-0018 D2 retired `.claude/Dev10x/session.yaml`, and the migrator
deliberately refuses to fold one over live config — so a leftover
survives every maintenance pass. It is inert only while a
`friction.yaml` `projects[]` entry shadows it; the moment one stops
matching, its residual v1 keys become the tier-2 read and trip the
`legacy_policy_keys` refusal.

Severity therefore tracks consequence, not tidiness, and these tests
pin that distinction: a file carrying v1 keys is critical, a bare
leftover is drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.skills.doctor.registry import load_strategies
from dev10x.skills.doctor.strategies.retired_session_yaml import (
    STRATEGY,
    detect,
)
from dev10x.skills.doctor.strategy import Context

_CONTRADICTORY = """\
friction_level: adaptive
active_modes: []  # review-deferred cleared — PR #814 merged
branch: janusz/GH-797/pap-domain-refactor-bundle
"""


def _bare_checkout(tmp_path: Path) -> Context:
    """A project with a settings file and no leftover beside it."""
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True)
    settings = claude / "settings.local.json"
    settings.write_text("{}", encoding="utf-8")
    return Context(settings_paths=(settings,))


def _checkout(tmp_path: Path, *, session_yaml: str) -> Context:
    """A project whose settings file sits beside a retired-path leftover."""
    context = _bare_checkout(tmp_path)
    retired = tmp_path / ".claude" / "Dev10x"
    retired.mkdir()
    (retired / "session.yaml").write_text(session_yaml, encoding="utf-8")
    return context


class TestDetection:
    def test_a_leftover_is_reported(self, tmp_path: Path) -> None:
        findings = detect(_checkout(tmp_path, session_yaml=_CONTRADICTORY))

        assert len(findings) == 1
        assert findings[0].strategy_id == "retired-session-yaml"

    def test_a_checkout_without_one_is_clean(self, tmp_path: Path) -> None:
        assert detect(_bare_checkout(tmp_path)) == []

    def test_one_settings_path_listed_twice_reports_once(self, tmp_path: Path) -> None:
        # Two entries can resolve to the same retired path; reporting the
        # same file twice would read as two leftovers.
        context = _checkout(tmp_path, session_yaml=_CONTRADICTORY)
        doubled = Context(settings_paths=context.settings_paths * 2)

        assert len(detect(doubled)) == 1

    def test_the_finding_names_the_file(self, tmp_path: Path) -> None:
        context = _checkout(tmp_path, session_yaml=_CONTRADICTORY)

        location = detect(context)[0].location

        assert location.endswith(".claude/Dev10x/session.yaml")

    def test_several_checkouts_are_each_reported(self, tmp_path: Path) -> None:
        # One settings path per project; a supervisor with many projects
        # needs every leftover named, not the first.
        first = _checkout(tmp_path / "a", session_yaml=_CONTRADICTORY)
        second = _checkout(tmp_path / "b", session_yaml=_CONTRADICTORY)
        merged = Context(settings_paths=first.settings_paths + second.settings_paths)

        assert len(detect(merged)) == 2


class TestSeverityTracksConsequence:
    def test_v1_keys_make_it_critical(self, tmp_path: Path) -> None:
        # `friction_level` is what the retired read-compat seam consumed;
        # a tier-2 read of this file is refused, not translated.
        findings = detect(_checkout(tmp_path, session_yaml=_CONTRADICTORY))

        assert findings[0].severity == "critical"

    def test_the_evidence_names_the_offending_key(self, tmp_path: Path) -> None:
        findings = detect(_checkout(tmp_path, session_yaml=_CONTRADICTORY))

        assert "friction_level" in findings[0].evidence

    @pytest.mark.parametrize(
        ("body", "expected_key"),
        [
            ("friction_level: adaptive\n", "friction_level"),
            ("walk_away: true\n", "walk_away"),
            ("active_modes: [solo-maintainer]\n", "active_modes: solo-maintainer"),
            ("gate_preset: strict\n", "gate_preset: strict"),
        ],
    )
    def test_every_v1_key_forces_critical(
        self, tmp_path: Path, body: str, expected_key: str
    ) -> None:
        # `legacy_policy_keys` takes five inputs and the fixture above
        # exercises one. `active_modes: solo-maintainer` in particular is
        # the common real-world trigger, and was reaching the grader as [].
        findings = detect(_checkout(tmp_path, session_yaml=body))

        assert findings[0].severity == "critical"
        assert expected_key in findings[0].evidence

    @pytest.mark.parametrize(
        "body",
        ["gate_preset: adaptive\n", "gate_overlays: [afk]\n"],
    )
    def test_the_current_schema_is_not_legacy(self, tmp_path: Path, body: str) -> None:
        # `gate_preset`/`gate_overlays` are the v2 spelling. Only a preset
        # naming a RETIRED posture counts, so a file speaking v2 is drift.
        findings = detect(_checkout(tmp_path, session_yaml=body))

        assert findings[0].severity == "drift"

    def test_a_materialised_overlay_clears_the_mode(self, tmp_path: Path) -> None:
        # The migrated shape: the migrator materialises the overlay and
        # leaves active_modes alone, so the mode is stated twice and the
        # overlay would not be dropped. That is not a legacy config.
        body = "active_modes: [solo-maintainer]\ngate_overlays: [solo-maintainer]\n"

        findings = detect(_checkout(tmp_path, session_yaml=body))

        assert findings[0].severity == "drift"

    @pytest.mark.parametrize(
        "body",
        ["branch: some/branch\n", "tickets: [GH-1]\n", "{}\n"],
    )
    def test_a_leftover_without_v1_keys_is_drift(self, tmp_path: Path, body: str) -> None:
        findings = detect(_checkout(tmp_path, session_yaml=body))

        assert findings[0].severity == "drift"

    @pytest.mark.parametrize(
        "body",
        ["::: not yaml :::\n", "- a\n- list\n", "just a string\n"],
    )
    def test_an_unparsable_leftover_is_critical(self, tmp_path: Path, body: str) -> None:
        # It must not crash the doctor — and it must not be graded as the
        # mildest finding either. "No keys" is the evidence for "harmless,
        # shadowed by the global file", and a file nobody can parse has not
        # earned that reading: a tier-2 read of it fails outright.
        findings = detect(_checkout(tmp_path, session_yaml=body))

        assert len(findings) == 1
        assert findings[0].severity == "critical"

    def test_the_unparsable_evidence_says_why(self, tmp_path: Path) -> None:
        findings = detect(_checkout(tmp_path, session_yaml="::: not yaml :::\n"))

        assert "could not be parsed" in findings[0].evidence


class TestRemediation:
    def test_it_delegates_to_plugin_maintenance(self, tmp_path: Path) -> None:
        finding = detect(_checkout(tmp_path, session_yaml=_CONTRADICTORY))[0]

        remediation = STRATEGY.remediate(finding)

        assert remediation.kind == "delegate_skill"
        assert remediation.target == "Dev10x:plugin-maintenance"

    def test_it_carries_the_path_to_remove(self, tmp_path: Path) -> None:
        finding = detect(_checkout(tmp_path, session_yaml=_CONTRADICTORY))[0]

        remediation = STRATEGY.remediate(finding)

        assert remediation.action["path"] == finding.location

    def test_it_records_which_keys_forced_the_severity(self, tmp_path: Path) -> None:
        finding = detect(_checkout(tmp_path, session_yaml=_CONTRADICTORY))[0]

        remediation = STRATEGY.remediate(finding)

        assert remediation.action["legacy_keys"] == ["friction_level"]


class TestRegistration:
    def test_the_doctor_loads_it_by_default(self) -> None:
        # A strategy absent from DEFAULT_STRATEGY_MODULES never runs, so
        # the detection above would be dead code without this.
        assert "retired-session-yaml" in [strategy.id for strategy in load_strategies()]
