"""Tests for the PAP-4 maintenance re-platforming (GH-801).

Parity is the acceptance criterion: the ported flows (worktree seed,
worktree→main sync, doctor queries) behave exactly as before — the
Policy objects carry provenance the string pipeline dropped.
"""

from __future__ import annotations

from dev10x.domain.common.policy import (
    PolicyAssessment,
    PolicyEffect,
    PolicyLifecycle,
    PolicySource,
)
from dev10x.skills.permission.doctor import Catalog, DeprecationOutcome
from dev10x.skills.permission.merge_worktree_permissions import sync_candidates_as_policies
from dev10x.skills.permission.policy_authoring import (
    CANDIDATE_TIER,
    policy_from_accepted_prompt,
)


class TestPolicyFromAcceptedPrompt:
    def test_accepted_prompt_becomes_candidate_policy(self) -> None:
        policy = policy_from_accepted_prompt(
            rule="Bash(make lint:*)",
            source=PolicySource.USER_PRIVATE,
            rationale="accepted during session abc",
        )
        assert policy.signature == "Bash(make lint:*)"
        assert policy.id == "Bash(make lint:*)"
        assert policy.source is PolicySource.USER_PRIVATE
        assert policy.effect is PolicyEffect.ALLOW
        assert policy.lifecycle is PolicyLifecycle.CANDIDATE
        assert policy.tier == CANDIDATE_TIER
        assert policy.rationale == "accepted during session abc"


class TestSyncCandidatesAsPolicies:
    def test_stable_entries_become_project_local_candidates(self) -> None:
        policies = sync_candidates_as_policies(entries=["Bash(make docs:*)"])
        (policy,) = policies
        assert policy.source is PolicySource.PROJECT_LOCAL
        assert policy.lifecycle is PolicyLifecycle.CANDIDATE
        assert policy.rationale == "worktree sync (GH-603)"

    def test_noise_entries_are_dropped_from_the_policy_set(self) -> None:
        entries = [
            "Bash(make docs:*)",
            "Bash(cat /tmp/x.AbCdEfGh1234.txt)",
        ]
        policies = sync_candidates_as_policies(entries=entries)
        assert [p.signature for p in policies] == ["Bash(make docs:*)"]

    def test_empty_input_yields_empty_set(self) -> None:
        assert sync_candidates_as_policies(entries=[]) == []


class TestDoctorPolicyQueries:
    def test_catalog_policies_returns_typed_entries(self) -> None:
        catalog = Catalog(
            version=1,
            last_audited="2026-01-01",
            groups={
                "git-core": {"tier": 1, "rules": ["Bash(git status:*)"]},
                "danger": {"tier": 3, "effect": "deny", "rules": ["Bash(sudo:*)"]},
            },
            deprecations=[],
            invariants=[],
        )
        policies = catalog.policies()
        assert [p.signature for p in policies] == ["Bash(git status:*)", "Bash(sudo:*)"]
        assert policies[0].group == "git-core"
        assert policies[1].effect is PolicyEffect.DENY

    def test_deprecation_outcome_records_as_assessment(self) -> None:
        outcome = DeprecationOutcome(
            rule="Bash(old:*)",
            action="replace",
            replacement="Bash(new:*)",
            reason="renamed in v2",
        )
        assert outcome.as_assessment() == PolicyAssessment(
            kind="doctor-deprecation",
            verdict="replace:Bash(new:*)",
            note="renamed in v2",
        )

    def test_removal_outcome_has_bare_action_verdict(self) -> None:
        outcome = DeprecationOutcome(rule="Bash(old:*)", action="remove", reason="retired")
        assert outcome.as_assessment().verdict == "remove"
