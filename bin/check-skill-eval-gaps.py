#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Scan skills/ for gated skills shipping zero eval assertions (GH-835).

Usage:
    bin/check-skill-eval-gaps.py [--all] [SKILL_DIR ...]

Modes:
    No args, not --all  → scan every skill under skills/ (default)
    ``--all``           → same as no args — scan every skill under skills/
    SKILL_DIR ...        → scan only the named skill directories

Exits with status 1 if any gated skill has missing or empty eval coverage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dev10x.skills.audit import eval_gaps  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skill_dirs",
        nargs="*",
        type=Path,
        help="Specific skill directories to scan (default: all of skills/)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan every skill under skills/ (default behavior)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.skill_dirs and not args.all:
        gaps = []
        for skill_dir in args.skill_dirs:
            if not (skill_dir / "SKILL.md").is_file():
                continue
            gap = eval_gaps.check_skill(skill_dir)
            if gap is not None:
                gaps.append(gap)
        scanned = len(args.skill_dirs)
    else:
        skills_root = REPO_ROOT / "skills"
        gaps = eval_gaps.scan_skills_root(skills_root)
        scanned = len(eval_gaps.find_skill_dirs(skills_root))

    if not gaps:
        print(f"OK — scanned {scanned} skill(s), no eval-coverage gaps found.")
        return 0

    print(
        f"Found {len(gaps)} gated skill(s) with missing/empty eval coverage "
        f"(scanned {scanned}):\n",
        file=sys.stderr,
    )
    for gap in gaps:
        print(f"- {gap.format()}", file=sys.stderr)

    print(
        "\nEvery skill with a REQUIRED AskUserQuestion gate must ship "
        "evals/evals.json with at least one gate-enforcement assertion. "
        "See .claude/rules/skill-gates.md and references/eval-schema.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
