#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Scan skill docs for raw CLI usage that should route through MCP/Skill wrappers.

Usage:
    bin/check-skill-cli-friction.py [--all] [PATH ...]

Modes:
    No paths given      → read newline-separated paths from stdin
    Paths given         → scan those files
    ``--all``           → scan every skill doc under ``skills/`` plus the
                          repo-root ``references/`` tree

Exits with status 1 if any violation is found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dev10x.skills.audit import cli_friction  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files to scan (default: read from stdin)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan every skill doc under skills/",
    )
    return parser.parse_args(argv)


def _resolve_paths(args: argparse.Namespace) -> list[Path]:
    if args.all:
        return cli_friction.find_target_files(
            REPO_ROOT / "skills"
        ) + cli_friction.find_shared_reference_files(REPO_ROOT / "references")
    if args.paths:
        return list(args.paths)
    if sys.stdin.isatty():
        return []
    return [Path(line.strip()) for line in sys.stdin if line.strip()]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    paths = _resolve_paths(args)
    # Filter to files the scanner targets — silently drop unrelated paths
    # (e.g., a PR that touches both ``skills/`` and ``src/``).
    target_paths = [p for p in paths if p.is_file() and cli_friction.is_target_file(p)]
    if not target_paths:
        print("No skill docs to scan.", file=sys.stderr)
        return 0

    violations = cli_friction.scan_paths(target_paths)
    if not violations:
        print(f"OK — scanned {len(target_paths)} file(s), no CLI-friction violations.")
        return 0

    print(
        f"Found {len(violations)} CLI-friction violation(s) "
        f"across {len({v.path for v in violations})} file(s):\n",
        file=sys.stderr,
    )
    for v in violations:
        print(v.format(), file=sys.stderr)
        print(file=sys.stderr)

    print(
        "Suppress an intentional case with an inline marker on the offending line:\n"
        "    `# cli-friction: allow <rule-id> — reason`\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
