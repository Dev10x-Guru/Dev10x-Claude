"""Every grouped baseline rule must reach the seeding path (GH-1313).

``skills/upgrade-cleanup/projects.yaml`` is the authoritative permission
catalog — it is the one on the write path. ``baseline-permissions.yaml``
carries a second, comparably-sized ``groups:`` block that ``ensure_base``
never reads, so a rule can be catalogued there, cited by skills, relied
on by hooks, and still prompt on every call. GH-1100's E18 (a ``cp`` rule
excepting a hard-deny) and E19 (``git nopager``) are that bug twice.

The guard below closes the class: a grouped rule is either seeded, or in
an opt-in group, or named in ``RULES_NOT_SEEDED`` with a reason.

The remaining tests are counter-checks, and they are the point of
GH-1215. That ticket records ``test_catalog_covers_mcp_tools``'s own
discovery narrowed to five of twelve modules — passing 3/3 while blind to
four fifths of its surface. A guard only sees what its enumeration sees,
so each side of this comparison is measured a second way:

- ``test_enumeration_finds_every_declared_rule`` counts rule lines in the
  raw YAML text and asserts the parser found at least that many, so a
  group shape the walker skips fails loudly.
- ``test_every_rule_bearing_section_is_folded`` asserts the seeded side
  reads every rule-bearing section of ``projects.yaml``, so a section
  added later cannot make unseeded rules look seeded — or unseeded ones
  unreadable.
- ``test_opt_in_groups_are_all_tier_three`` pins the exclusion to the
  catalog's own tier tags, so re-tagging a seeded group cannot quietly
  remove it from the guard's field of view.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import dev10x.skills.permission as permission_pkg
from dev10x.domain.common.baseline_catalog import load_baseline_dict
from dev10x.skills.permission.baseline_coverage import (
    BACKLOG_STARTING_SIZE,
    FLAT_SECTIONS,
    KEYED_SECTIONS,
    OPT_IN_GROUPS,
    RULES_NOT_SEEDED,
    UNTRIAGED_BACKLOG,
    enumerate_baseline_rules,
    rule_bearing_sections,
    seeded_rules,
    triaged_backlog,
    unseeded_baseline_rules,
)
from dev10x.skills.permission.catalog_paths import CATALOG_RELPATH

PERMISSION_DIR = Path(permission_pkg.__file__).resolve().parent
REPO_ROOT = PERMISSION_DIR.parents[3]
BASELINE_YAML = PERMISSION_DIR / "baseline-permissions.yaml"
PROJECTS_YAML = REPO_ROOT / CATALOG_RELPATH

#: A rule entry inside a group's ``rules:`` list. Six-space indent is the
#: only depth a rule sits at; ``deprecations:`` and ``invariants:`` are
#: top-level sequences at two spaces and do not match.
_RULE_LINE = re.compile(r"^      - \S", re.MULTILINE)


def _baseline() -> dict:
    return load_baseline_dict(BASELINE_YAML, strict=True)


def _projects() -> dict:
    return yaml.safe_load(PROJECTS_YAML.read_text(encoding="utf-8"))


def test_every_baseline_rule_is_seeded_or_explicitly_excluded() -> None:
    unseeded = unseeded_baseline_rules(catalog=_baseline(), config=_projects())
    assert not unseeded, (
        "these rules exist in baseline-permissions.yaml but no seeding path "
        "can deliver them, so every caller will prompt (GH-1100 E18/E19) — "
        "add them to skills/upgrade-cleanup/projects.yaml, or to "
        "RULES_NOT_SEEDED in baseline_coverage.py with the reason they are "
        "deliberately withheld. Do NOT append to UNTRIAGED_BACKLOG: it "
        "records divergence that predates this guard and may only shrink.\n"
        + "\n".join(f"  {entry.group} (tier {entry.tier}): {entry.rule}" for entry in unseeded)
    )


def test_exclusion_list_names_only_declared_rules() -> None:
    declared = {entry.rule for entry in enumerate_baseline_rules(catalog=_baseline())}
    stale = set(RULES_NOT_SEEDED) - declared
    assert not stale, (
        "RULES_NOT_SEEDED names rules absent from baseline-permissions.yaml — "
        "a renamed or deleted rule left behind here would excuse a real gap "
        "for its replacement:\n" + "\n".join(sorted(stale))
    )


def test_backlog_only_shrinks() -> None:
    assert len(UNTRIAGED_BACKLOG) <= BACKLOG_STARTING_SIZE, (
        f"UNTRIAGED_BACKLOG has grown to {len(UNTRIAGED_BACKLOG)} from its "
        f"{BACKLOG_STARTING_SIZE}-rule starting point. It is a ratchet over "
        "divergence that predates the guard, not a place to park new "
        "divergence — ship the rule in projects.yaml or give it a reason in "
        "RULES_NOT_SEEDED instead."
    )


def test_backlog_carries_no_resolved_entries() -> None:
    resolved = triaged_backlog(catalog=_baseline(), config=_projects())
    assert not resolved, (
        "these rules no longer need triage — they are seeded, documented in "
        "RULES_NOT_SEEDED, or gone from the grouped catalog. Drop them from "
        "UNTRIAGED_BACKLOG so the remaining debt is countable:\n" + "\n".join(sorted(resolved))
    )


def test_enumeration_finds_every_declared_rule() -> None:
    declared = len(_RULE_LINE.findall(BASELINE_YAML.read_text(encoding="utf-8")))
    found = len(enumerate_baseline_rules(catalog=_baseline()))
    assert declared > 0, f"no rule lines found in {BASELINE_YAML}"
    assert found >= declared, (
        f"enumerate_baseline_rules found {found} rules but {declared} rule "
        f"lines exist in {BASELINE_YAML}. The walker is skipping groups — a "
        "narrowed enumeration makes the coverage guard pass green while blind "
        "to the rules it cannot see (GH-1215)."
    )


def test_every_rule_bearing_section_is_folded() -> None:
    folded = set(FLAT_SECTIONS) | set(KEYED_SECTIONS)
    unfolded = rule_bearing_sections(config=_projects()) - folded
    assert not unfolded, (
        "skills/upgrade-cleanup/projects.yaml carries rule-bearing sections "
        "that baseline_coverage does not fold into the seeded set:\n"
        + "\n".join(sorted(unfolded))
        + "\nAdd each to FLAT_SECTIONS or KEYED_SECTIONS if ensure_base ships "
        "it, so its rules are not reported as unreachable."
    )


def test_opt_in_groups_are_all_tier_three() -> None:
    tiers = {entry.group: entry.tier for entry in enumerate_baseline_rules(catalog=_baseline())}
    misfiled = {group: tiers[group] for group in OPT_IN_GROUPS if tiers.get(group, 3) != 3}
    assert not misfiled, (
        "OPT_IN_GROUPS excuses these groups from the coverage guard, but they "
        "are no longer tier 3 — a seeded tier is not opt-in, so excusing it "
        "hides a real gap:\n"
        + "\n".join(f"  {group}: tier {tier}" for group, tier in sorted(misfiled.items()))
    )


def test_opt_in_groups_all_exist() -> None:
    groups = {entry.group for entry in enumerate_baseline_rules(catalog=_baseline())}
    stale = OPT_IN_GROUPS - groups
    assert not stale, (
        "OPT_IN_GROUPS names groups absent from baseline-permissions.yaml — a "
        "renamed group left behind here excuses nothing and hides its "
        "successor:\n" + "\n".join(sorted(stale))
    )


def test_seeded_rules_covers_every_tracker() -> None:
    # A per-tracker block is reachable for whichever tracker a user pinned,
    # so folding only the resolved one would report the other trackers'
    # rules as unreachable. Linear is the default; Jira proves the fold is
    # not accidentally single-tracker.
    seeded = seeded_rules(config=_projects())
    trackers = _projects().get("tracker_permissions") or {}
    for name, rules in trackers.items():
        assert set(rules or []) <= seeded, (
            f"tracker block {name!r} is not folded into seeded_rules"
        )
