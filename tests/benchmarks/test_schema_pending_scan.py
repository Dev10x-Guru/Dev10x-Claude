"""Benchmark: the SessionStart config-schema staleness scan (GH-1252).

``build_install_check_context`` gained a second signal — whether the
durable ``friction.yaml`` still carries pre-ADR-0022 keys — because the
banner previously promised to "migrate config files" while gating on a
bare plugin-version comparison it could not relate to config state.

That signal runs on **every** session start, in an orchestrator that
already parses ``friction.yaml`` once for the friction-setup nudge, so
its cost is worth pinning under the same 20%-mean CI gate that guards
hook latency (``.claude/rules/performance.md``).

A note on what these numbers are *not*. An earlier draft skipped the
parse whenever no retired key appeared in the store's raw bytes, and
this module claimed ~20µs for the migrated case on that basis. The
optimization was dead on arrival: the ``active_modes`` leg of the
residue predicate forced ``active_modes`` into the marker set, and that
key is present in virtually every real entry — so the scan always
matched and always parsed. Because these benchmarks assert only the
returned count, they passed while the saving they documented did not
exist. The parse is now made cheap at the source instead (libyaml
loader), and both paths below cost roughly the same, which is the honest
shape of the code.

Expect roughly: migrated and stale both ~2ms (parse-dominated), absent
~1µs. If a future change reintroduces a short-circuit, assert the
*timing* difference here rather than trusting a docstring.

The fixture is sized to a real userspace store (~95 project entries,
~19KB) rather than a toy file — the parse cost is dominated by document
size, so a two-entry fixture would measure nothing useful.

Run:
    pytest tests/benchmarks/test_schema_pending_scan.py --benchmark-only
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.domain.config_migration import schema_v2_pending

_ENTRY_COUNT = 95


def _render_store(*, stale: bool) -> str:
    """Render a friction.yaml of realistic size.

    ``stale`` decides whether entries carry the retired ``friction_level``
    key, so the already-migrated path (the overwhelmingly common one in
    the field) and the needs-migration path are measured separately.
    """
    lines = ["defaults:", "  supervisor_review: required", "  active_modes: []", "projects:"]
    for index in range(_ENTRY_COUNT):
        lines.append(f"  - match: ['*/repo-{index}', '*/repo-{index}-*']")
        lines.append("    tracker: github")
        lines.append("    gate_overlays: [solo-maintainer, afk]")
        lines.append("    active_modes: [solo-maintainer]")
        if stale:
            lines.append("    friction_level: adaptive")
        else:
            lines.append("    supervisor_review: none")
    return "\n".join(lines) + "\n"


@pytest.mark.benchmark(group="session-start-schema-scan")
class TestSchemaPendingScanBenchmark:
    @pytest.fixture(scope="class")
    def migrated_store(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        path = tmp_path_factory.mktemp("migrated") / "friction.yaml"
        path.write_text(_render_store(stale=False))
        return path

    @pytest.fixture(scope="class")
    def stale_store(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        path = tmp_path_factory.mktemp("stale") / "friction.yaml"
        path.write_text(_render_store(stale=True))
        return path

    def test_scan_of_migrated_store(self, benchmark, migrated_store: Path) -> None:
        assert benchmark(lambda: schema_v2_pending(path=migrated_store)) == 0

    def test_scan_of_stale_store(self, benchmark, stale_store: Path) -> None:
        assert benchmark(lambda: schema_v2_pending(path=stale_store)) == _ENTRY_COUNT

    def test_scan_of_absent_store(self, benchmark, tmp_path: Path) -> None:
        missing = tmp_path / "nope" / "friction.yaml"
        assert benchmark(lambda: schema_v2_pending(path=missing)) == 0
