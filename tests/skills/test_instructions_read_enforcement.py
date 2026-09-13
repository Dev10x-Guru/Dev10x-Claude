"""A skill whose contract cannot be read in one call must say so (GH-1279).

Several SKILL.md files delegate to an `instructions.md` with "Read it
now and follow it end-to-end". For most skills that instruction is
achievable: the file fits in a single `Read`. For the largest it is
not — the call returns a truncated `PARTIAL view` and an agent that
stops there is working from part of the contract while believing it
holds all of it.

GH-1279 caught exactly that on `Dev10x:work-on`: 57% of the file went
unread, and the Plan Completion Gate, the pre-gate checklist and the
merge-gated completion rule — all of which live in the tail — never
fired. The audit's own report then made a claim about the skill that
the unread half contradicted.

The enforcement block was attached to the two skills whose files fit,
and missing from the ones where the failure is structural. These tests
pin the invariant the other way round: the block is required exactly
where a single `Read` is not enough.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILLS = Path(__file__).parents[2] / "skills"

_ENFORCEMENT_MARKER = "End-to-end read enforcement"

# Measured, not assumed. Two truncation notices from real `Read` calls:
#   work-on  124_747 bytes -> 48_920 tokens  (2.551 chars/token)
#   fanout    64_797 bytes -> 25_502 tokens  (2.541 chars/token)
# Markdown this dense runs ~2.5 chars/token rather than the usual ~4,
# so the 25k-token cap lands near 63.5 KB of prose like these two.
_OBSERVED_TRUNCATIONS = ((124_747, 48_920), (64_797, 25_502))
_CHARS_PER_TOKEN = 2.54
_READ_TOKEN_CAP = 25_000

# The threshold deliberately sits BELOW the measured cap. Two reasons,
# both learned from the first cut of this guard sitting at the cap:
#
#  1. The ratio came from two files. A denser one tokenizes worse, and
#     a file estimated safe at 2.54 that really runs at 2.3 truncates
#     unguarded. The margin buys room for that error.
#  2. At the cap, skill-audit cleared the bar by 2.8% and fanout by
#     2.0% — so trimming ~1.3 KB from either dropped it out of the
#     guard and NOTHING failed. A boundary inside its own noise
#     protects whichever files happen to sit above it today.
#
# 0.8 puts the line at ~50.8 KB, in the gap between gh-pr-respond
# (57.2 KB, guarded) and gh-pr-monitor (46.6 KB, not) — about 11%
# clear on both sides rather than 2%.
_SAFETY_MARGIN = 0.8
_SINGLE_READ_BYTES = int(_CHARS_PER_TOKEN * _READ_TOKEN_CAP * _SAFETY_MARGIN)


def _instruction_files() -> list[Path]:
    return sorted(_SKILLS.glob("*/instructions.md"))


def _oversized() -> list[Path]:
    return [path for path in _instruction_files() if path.stat().st_size > _SINGLE_READ_BYTES]


def _skill_md(instructions: Path) -> Path:
    return instructions.parent / "SKILL.md"


def test_some_instruction_file_is_oversized() -> None:
    """Non-vacuity: the guard must actually have subjects.

    Without this, extracting every large file would leave the
    parametrized test below passing over an empty list — green because
    it checks nothing, which is the failure mode GH-1215 documents.
    """
    assert _oversized(), (
        "no instructions.md exceeds a single Read — if that is genuinely "
        "true now, this guard has served its purpose and can go"
    )


@pytest.mark.parametrize("instructions", _oversized(), ids=lambda path: path.parent.name)
def test_oversized_instructions_carry_read_enforcement(instructions: Path) -> None:
    skill_md = _skill_md(instructions)
    size = instructions.stat().st_size

    assert _ENFORCEMENT_MARKER in skill_md.read_text(encoding="utf-8"), (
        f"{instructions.parent.name}/instructions.md is {size:,} bytes — over the "
        f"~{_SINGLE_READ_BYTES:,} a single Read returns — so 'follow it end-to-end' "
        f"is unachievable in one call. Add an '{_ENFORCEMENT_MARKER}' block to "
        f"{skill_md.name} telling the agent to page with Read(offset=…) to the end."
    )


@pytest.mark.parametrize("instructions", _instruction_files(), ids=lambda path: path.parent.name)
def test_skill_md_delegating_to_instructions_exists(instructions: Path) -> None:
    # The guard reads SKILL.md next to each instructions.md; a missing
    # sibling would make the check above silently unenforceable.
    assert _skill_md(instructions).is_file()


class TestTheThresholdMatchesObservedTruncation:
    """Pin the ratio to the two truncation notices it came from.

    Against the RECORDED observations, never against the live files. An
    earlier cut read `work-on/instructions.md` off disk, which coupled
    the calibration to a document under active edit: changing that file
    by more than 5% failed a test whose message is about chars-per-token
    drift, blaming the edit for something it had nothing to do with.
    The observations are historical facts and belong here as literals.
    """

    @pytest.mark.parametrize(("observed_bytes", "observed_tokens"), _OBSERVED_TRUNCATIONS)
    def test_the_ratio_reproduces_each_observation(
        self, observed_bytes: int, observed_tokens: int
    ) -> None:
        estimated = observed_bytes / _CHARS_PER_TOKEN

        # Within 5%: the ratio is an estimate, but one drifting from both
        # recorded notices would put the threshold somewhere unmeasured.
        assert abs(estimated - observed_tokens) / observed_tokens < 0.05

    def test_the_threshold_stays_under_the_measured_cap(self) -> None:
        # The margin is the point: a threshold at or above the cap offers
        # no room for a denser file than the two that were measured.
        assert _SINGLE_READ_BYTES < _CHARS_PER_TOKEN * _READ_TOKEN_CAP

    def test_a_file_known_to_read_whole_is_under_the_threshold(self) -> None:
        # git-commit's instructions.md returned all 1180 lines in one
        # call, so a threshold that flagged it would be a false positive.
        # This one DOES read the live file on purpose — it is the guard
        # against lowering the margin until real files trip it.
        size = (_SKILLS / "git-commit" / "instructions.md").stat().st_size

        assert size < _SINGLE_READ_BYTES
