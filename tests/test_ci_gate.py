"""Pin the always-runs CI gate's semantics (GH-1298, ADR-0024).

A required status check that a ``paths:`` filter kept from running never
reports, and GitHub holds the pull request at "Expected — waiting for status
to be reported" forever. ``ci-gate.yml`` resolves that by moving the path
filter from the event to the job and aggregating the results, which puts the
whole guarantee in two places: the aggregator must accept ``skipped``, and it
must still refuse to pass when *nothing* ran.

Getting that backwards is worse than having no gate — an aggregator that goes
green while a real leg failed makes every future merge gate lie — so the
failed, skipped and mixed cases are exercised here against the actual script
the workflow runs, rather than being asserted by reading the YAML.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).parents[1]
_VERDICT_SCRIPT = _REPO_ROOT / ".github" / "scripts" / "ci-gate-verdict.sh"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci-gate.yml"

#: Jobs the gate aggregates. ``changes`` is included deliberately: it is the
#: one dependency with no ``if:``, so it is what keeps an all-skipped run from
#: passing vacuously.
_EXPECTED_NEEDS = {"changes", "hook-tests", "server-tests", "floors"}

#: Path-filtered legs — each must be able to report ``skipped``.
_FILTERED_LEGS = ("hook-tests", "server-tests", "floors")


def _verdict(*, results: str) -> int:
    completed = subprocess.run(
        [str(_VERDICT_SCRIPT)],
        cwd=_REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "CI_GATE_RESULTS": results},
        capture_output=True,
        timeout=30,
    )
    return completed.returncode


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def jobs(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]


@pytest.fixture(scope="module")
def gate(jobs: dict[str, Any]) -> dict[str, Any]:
    return jobs["ci-gate"]


class TestVerdictAcceptsWhatPathFilteringProduces:
    @pytest.mark.parametrize(
        "results",
        [
            "success success success success",
            "success skipped skipped skipped",
            "success success skipped",
            "success skipped success skipped",
        ],
    )
    def test_success_and_skipped_pass(self, results: str) -> None:
        assert _verdict(results=results) == 0


class TestVerdictRefusesEverythingElse:
    @pytest.mark.parametrize(
        "results",
        [
            "success failure skipped",
            "failure failure failure",
            "success cancelled skipped",
            "success success timed_out",
            "skipped failure",
        ],
    )
    def test_a_non_skipped_non_success_fails(self, results: str) -> None:
        assert _verdict(results=results) == 1

    @pytest.mark.parametrize("results", ["skipped", "skipped skipped skipped", "", "   "])
    def test_nothing_actually_ran_fails(self, results: str) -> None:
        """An all-skipped or empty result set must not pass vacuously."""
        assert _verdict(results=results) == 1


class TestWorkflowWiring:
    def test_gate_has_no_event_path_filter(self, workflow: dict[str, Any]) -> None:
        """A ``paths:`` filter is exactly what stops a check from reporting."""
        # ``on`` is parsed as the YAML boolean True by safe_load.
        triggers = workflow[True]
        assert "paths" not in triggers["pull_request"]
        assert "paths" not in triggers["push"]

    def test_gate_runs_even_when_every_dependency_skips(self, gate: dict[str, Any]) -> None:
        assert gate["if"] == "always()"

    def test_gate_aggregates_every_substantive_leg(self, gate: dict[str, Any]) -> None:
        assert set(gate["needs"]) == _EXPECTED_NEEDS

    def test_gate_delegates_the_decision_to_the_tested_script(self, gate: dict[str, Any]) -> None:
        commands = [step.get("run", "") for step in gate["steps"]]
        assert any(".github/scripts/ci-gate-verdict.sh" in command for command in commands)

    @pytest.mark.parametrize("leg", _FILTERED_LEGS)
    def test_filtered_legs_are_gated_at_job_level(self, jobs: dict[str, Any], leg: str) -> None:
        """Job-level ``if:`` yields ``skipped``; event-level ``paths:`` yields
        nothing at all."""
        assert jobs[leg]["if"].startswith("needs.changes.outputs.")

    def test_classifier_job_is_unconditional(self, jobs: dict[str, Any]) -> None:
        assert "if" not in jobs["changes"]

    @pytest.mark.parametrize("retired", ["pytest-hooks.yml", "pytest-servers.yml"])
    def test_the_ambiguous_test_context_is_gone(self, retired: str) -> None:
        """Both files emitted a check literally named ``test``, so neither name
        could be required unambiguously (ADR-0024)."""
        assert not (_REPO_ROOT / ".github" / "workflows" / retired).exists()
