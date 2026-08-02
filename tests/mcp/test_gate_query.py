"""Tests for the service-layer GateResolutionQuery (GH-840).

The read+compute half of gate resolution now lives in a query object that
returns an assembled GateContext + resolution, testable without the MCP
adapter's side effects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.domain.common.result import ErrorResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.gate_policy import GateContext
from dev10x.mcp.gate_query import GateResolutionOutcome, GateResolutionQuery
from dev10x.session import preset_pin


def _write_config(toplevel: Path, body: str) -> None:
    # Durable keys (friction_level / active_modes / allowed_overlays) are read
    # from the gitignored config.yaml, not session.yaml (GH-805).
    path = toplevel / ".claude" / "Dev10x" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _write_friction(projects: list[dict]) -> None:
    """Write the global friction.yaml (isolated to a tmp home by conftest).

    ``human_review: false`` sits in ``defaults`` — and so merges into every
    matched entry — because these tests probe policy INHERITANCE through the
    merge gate. Left at its safe default the ADR-0019 precondition floor
    (GH-1000) would resolve every one of them to ``ask``, hiding whatever
    the preset actually inherited. The floor's own behaviour is covered in
    ``tests/domain/test_gate_policy.py`` and ``tests/mcp/test_gate_tools.py``.
    """
    path = Dev10xConfigDir.friction_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "defaults": {"gate_preset": "strict", "human_review": False},
                "projects": projects,
            }
        )
    )


async def _merge_effect(toplevel: Path) -> str:
    result = await GateResolutionQuery(gate="merge", context={}, toplevel=str(toplevel)).run()
    assert not isinstance(result, ErrorResult)
    return result.value.resolution.effect.value


class TestGateResolutionQuery:
    @pytest.mark.asyncio
    async def test_returns_outcome_with_assembled_context(self, tmp_path: Path) -> None:
        result = await GateResolutionQuery(gate="merge", context={}, toplevel=str(tmp_path)).run()
        assert not isinstance(result, ErrorResult)
        outcome = result.value
        assert isinstance(outcome, GateResolutionOutcome)
        assert isinstance(outcome.context, GateContext)
        assert outcome.resolution.gate == "merge"
        assert outcome.dropped_overlays == []

    @pytest.mark.asyncio
    async def test_unknown_context_field_ignored_not_errored(self, tmp_path: Path) -> None:
        # GH-854 F1: an unknown context key is dropped and surfaced, not
        # hard-failed — the gate still resolves on the remaining facts.
        result = await GateResolutionQuery(
            gate="merge", context={"vibe": "good"}, toplevel=str(tmp_path)
        ).run()
        assert not isinstance(result, ErrorResult)
        assert result.value.ignored_context_fields == ["vibe"]
        assert result.value.resolution.gate == "merge"

    @pytest.mark.asyncio
    async def test_known_and_unknown_fields_partitioned(self, tmp_path: Path) -> None:
        # A valid field is kept and applied; only the unknown one is dropped.
        result = await GateResolutionQuery(
            gate="batch_layout",
            context={"overlap_signals": 2, "typo_field": 1},
            toplevel=str(tmp_path),
        ).run()
        assert not isinstance(result, ErrorResult)
        assert result.value.ignored_context_fields == ["typo_field"]
        assert result.value.context.overlap_signals == 2

    @pytest.mark.asyncio
    async def test_session_adoption_computes_stale_onto_context(self, tmp_path: Path) -> None:
        # No explicit session_stale → the branch-only fallback is computed
        # and lands on the assembled context.
        result = await GateResolutionQuery(
            gate="session_adoption", context={}, toplevel=str(tmp_path)
        ).run()
        assert not isinstance(result, ErrorResult)
        assert isinstance(result.value.context.session_stale, bool)

    @pytest.mark.asyncio
    async def test_disallowed_overlay_is_dropped(self, tmp_path: Path) -> None:
        # allowed_overlays acts as an allow-list: solo-maintainer is not on it,
        # so the durable-mode guard drops it before resolution (GH-805).
        _write_config(
            tmp_path,
            "friction_level: adaptive\nactive_modes: [solo-maintainer]\nallowed_overlays: [afk]\n",
        )
        result = await GateResolutionQuery(gate="merge", context={}, toplevel=str(tmp_path)).run()
        assert not isinstance(result, ErrorResult)
        assert "solo-maintainer" in result.value.dropped_overlays


class TestWorktreePolicyInheritance:
    """A linked worktree resolves the REPO's durable policy (GH-978).

    ``pin_gate_preset`` keys entries off the git common dir, so a worktree
    whose directory name is not repo-shaped — an agent worktree at
    ``<repo>/.claude/worktrees/agent-<hash>`` — matched no entry and silently
    fell back to the ``strict`` baseline, walling unattended workers at the
    merge gate (PR #973 field case).
    """

    @pytest.fixture
    def repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A `bl-zebra` main checkout; every identity lookup resolves to it."""
        main = tmp_path / "work" / "bl-zebra"
        (main / ".git").mkdir(parents=True)
        monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: str(main / ".git"))
        return main

    @pytest.fixture
    def agent_worktree(self, repo: Path) -> Path:
        """A nested agent worktree — matches neither `*/x` nor `*/x-*`."""
        worktree = repo / ".claude" / "worktrees" / "agent-a194a6736f7f86b6c"
        worktree.mkdir(parents=True)
        return worktree

    @pytest.mark.asyncio
    async def test_agent_worktree_inherits_the_repo_pin(
        self, repo: Path, agent_worktree: Path
    ) -> None:
        """The AC: the worktree resolves the SAME effect as the main checkout."""
        _write_friction([{"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}])

        assert await _merge_effect(agent_worktree) == await _merge_effect(repo)
        # ...and that shared effect is the pinned adaptive posture, not the
        # strict baseline the worktree used to fall back to.
        assert await _merge_effect(agent_worktree) == "auto-advance"

    @pytest.mark.asyncio
    async def test_unpinned_repo_still_falls_back_to_defaults(
        self, repo: Path, agent_worktree: Path
    ) -> None:
        """Inheritance must not invent a policy: no entry → strict defaults."""
        _write_friction([{"match": ["*/some-other-repo"], "gate_preset": "adaptive"}])

        assert await _merge_effect(agent_worktree) == "ask"

    @pytest.mark.asyncio
    async def test_stale_worktree_config_loses_to_the_repo_pin(
        self, repo: Path, agent_worktree: Path
    ) -> None:
        """The literal #978 case: a stale copied config.yaml no longer wins."""
        _write_config(agent_worktree, "friction_level: strict\nactive_modes: []\n")
        _write_friction([{"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"}])

        assert await _merge_effect(agent_worktree) == "auto-advance"

    @pytest.mark.asyncio
    async def test_worktree_own_entry_still_wins(self, repo: Path, agent_worktree: Path) -> None:
        """Worktree-first ordering: a `dir`-scoped pin keeps its exact meaning."""
        _write_friction(
            [
                {"match": [str(agent_worktree)], "gate_preset": "strict"},
                {"match": ["*/bl-zebra", "*/bl-zebra-*"], "gate_preset": "adaptive"},
            ]
        )

        assert await _merge_effect(agent_worktree) == "ask"
        assert await _merge_effect(repo) == "auto-advance"

    @pytest.mark.asyncio
    async def test_degrades_to_toplevel_outside_a_git_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No common dir and no toplevel → resolve at the given path, no raise."""
        monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: None)
        monkeypatch.setattr(preset_pin, "_bounded_toplevel", lambda *, cwd: None)
        _write_friction([])

        assert await _merge_effect(tmp_path) == "ask"

    @pytest.mark.asyncio
    async def test_bare_repo_has_no_root_and_degrades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare common dir resolves an identity with `root: None`."""
        monkeypatch.setattr(preset_pin, "_common_dir", lambda *, cwd: "/srv/git/bl-zebra.git")
        _write_friction([{"match": ["*/bl-zebra"], "gate_preset": "adaptive"}])

        # No working tree to probe, so the worktree path governs → defaults.
        assert await _merge_effect(tmp_path) == "ask"
