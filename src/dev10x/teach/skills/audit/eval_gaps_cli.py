from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dev10x.core.paths import skill_roots
from dev10x.teach.skills.audit import eval_gaps

DESCRIPTION = "Scan skills for gated skills shipping zero eval assertions (GH-835)."


def _parse_args(*, argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "skill_dirs",
        nargs="*",
        type=Path,
        help="Specific skill directories to scan (default: every skill)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan every skill (default behavior)",
    )
    return parser.parse_args(argv)


def main(*, argv: list[str], repo_root: Path) -> int:
    args = _parse_args(argv=argv)

    if args.skill_dirs and not args.all:
        gaps = []
        scanned = 0
        for skill_dir in args.skill_dirs:
            if not (skill_dir / "SKILL.md").is_file():
                continue
            scanned += 1
            gap = eval_gaps.check_skill(skill_dir)
            if gap is not None:
                gaps.append(gap)
    else:
        roots = skill_roots(repo_root=repo_root)
        gaps = [gap for root in roots for gap in eval_gaps.scan_skills_root(root)]
        scanned = sum(len(eval_gaps.find_skill_dirs(root)) for root in roots)

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
