#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Verify audit completion for a repository.

Checks how many merged PRs have been audited (have the audit
trail marker) vs how many remain unaudited.
"""

import argparse
import json
import subprocess
import sys

AUDIT_MARKER = "PR Audit"

# GH-1414: a PEP 723 script runs isolated from the dev10x package and
# cannot reach its bounded subprocess helpers, so the bound is local.
_SUBPROCESS_TIMEOUT_SECONDS = 30


def run_gh(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(
            f"gh exceeded {_SUBPROCESS_TIMEOUT_SECONDS}s — treating as wedged",
            file=sys.stderr,
        )
        return ""
    if result.returncode != 0:
        print(f"gh error: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify PR audit completion",
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max PRs to check (default: 200)",
    )
    args = parser.parse_args()

    output = run_gh(
        [
            "pr",
            "list",
            "--repo",
            args.repo,
            "--state",
            "merged",
            "--limit",
            str(args.limit),
            "--json",
            "number,title",
        ]
    )
    if not output:
        print("No merged PRs found.")
        return 0

    prs = json.loads(output)
    audited = 0
    unaudited = 0

    for pr in prs:
        comments_output = run_gh(
            [
                "pr",
                "view",
                str(pr["number"]),
                "--repo",
                args.repo,
                "--json",
                "comments",
                "--jq",
                ".comments[].body",
            ]
        )
        if AUDIT_MARKER in comments_output:
            audited += 1
        else:
            unaudited += 1

    total = audited + unaudited
    pct = (audited / total * 100) if total else 0

    print(f"Audit Status for {args.repo}")
    print(f"  Total merged PRs checked: {total}")
    print(f"  Audited: {audited} ({pct:.0f}%)")
    print(f"  Unaudited: {unaudited}")

    if unaudited == 0:
        print("  All checked PRs have been audited.")
    else:
        print(f"  Run gh-unresolved-threads.py to scan remaining {unaudited} PRs.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
