#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Audit the codebase for external-service usage and privacy-policy drift (GH-6).

Usage:
    bin/check-privacy-policy.py [--inventory] [--all] [PATH ...]

Modes:
    No paths given      → read newline-separated paths from stdin
    Paths given         → audit those files
    ``--all``           → audit every source/skill/script tree
    ``--inventory``     → print a Markdown inventory regardless of violations

Exits with status 1 if any violation is found:

* A service detected in scanned files is missing from
  ``PRIVACY_POLICY.md``'s "Third-party integrations" table.
* A Python source file imports an outbound-network library
  (``requests``, ``httpx``, ``urllib.request``, ...) — the policy
  states no such calls are made from plugin code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dev10x.skills.audit import privacy  # noqa: E402

DEFAULT_SCAN_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "src",
    REPO_ROOT / "skills",
    REPO_ROOT / "plugins",
    REPO_ROOT / "bin",
    REPO_ROOT / "hooks",
    REPO_ROOT / "servers",
    REPO_ROOT / "commands",
    REPO_ROOT / ".github" / "workflows",
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files to audit (default: read from stdin)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Audit every default scan root",
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="Print the full inventory in Markdown",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=REPO_ROOT / "PRIVACY_POLICY.md",
        help="Path to PRIVACY_POLICY.md",
    )
    return parser.parse_args(argv)


def _resolve_paths(args: argparse.Namespace) -> list[Path]:
    if args.all:
        return list(DEFAULT_SCAN_ROOTS)
    if args.paths:
        return list(args.paths)
    if sys.stdin.isatty():
        return []
    return [Path(line.strip()) for line in sys.stdin if line.strip()]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    paths = _resolve_paths(args)
    if not paths:
        print("No paths to audit.", file=sys.stderr)
        return 0

    result = privacy.audit(scan_paths_=paths, policy_path=args.policy)

    if args.inventory:
        print(privacy.render_inventory_markdown(result))

    if not result.has_violations:
        scanned = len({u.path for u in result.usages})
        print(
            f"OK — {len(result.usages)} service reference(s) across "
            f"{scanned} file(s); all documented in PRIVACY_POLICY.md."
        )
        return 0

    if result.undocumented:
        print(
            f"\n[FAIL] Detected {len(result.undocumented)} undocumented service(s):",
            file=sys.stderr,
        )
        for service in sorted(result.undocumented):
            sample = next(u for u in result.usages if u.service == service)
            print(
                f"  - {service}: first seen at {sample.path}:{sample.line_number}",
                file=sys.stderr,
            )
        print(
            "\n  Add a row for each service to the 'Third-party integrations'\n"
            "  table in PRIVACY_POLICY.md, or suppress with an inline marker:\n"
            "      # privacy-audit: allow <service> — reason\n",
            file=sys.stderr,
        )

    if result.net_imports:
        print(
            f"\n[FAIL] Detected {len(result.net_imports)} outbound-network "
            f"import(s) in plugin source:",
            file=sys.stderr,
        )
        for violation in result.net_imports:
            print(f"  - {violation.format()}", file=sys.stderr)
        print(
            "\n  The privacy policy guarantees no outbound network calls from\n"
            "  plugin code. Remove the import or update PRIVACY_POLICY.md.\n",
            file=sys.stderr,
        )

    return 1


if __name__ == "__main__":
    sys.exit(main())
