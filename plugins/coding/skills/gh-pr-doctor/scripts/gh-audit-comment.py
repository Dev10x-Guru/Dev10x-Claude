#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Post audit trail comments on PRs from a mapping file.

Reads a JSON mapping of PR numbers to issue references and posts
a standardized audit comment on each PR. This enables incremental
re-runs — already-audited PRs are skipped by the scan script.

Input: JSON file with structure:
  [{"pr_number": 42, "issues": [{"number": 100, "title": "Security findings"}]}]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# GH-1414: a PEP 723 script runs isolated from the dev10x package and
# cannot reach its bounded subprocess helpers, so the bound is local.
_SUBPROCESS_TIMEOUT_SECONDS = 30


def post_comment(
    repo: str,
    pr_number: int,
    body: str,
) -> bool:
    try:
        result = subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body", body],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(
            f"Commenting on PR #{pr_number} exceeded "
            f"{_SUBPROCESS_TIMEOUT_SECONDS}s — treating as wedged",
            file=sys.stderr,
        )
        return False
    if result.returncode != 0:
        print(
            f"Failed to comment on PR #{pr_number}: {result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def format_comment(
    issues: list[dict],
) -> str:
    lines = ["PR Audit — unresolved threads tracked in:"]
    for issue in issues:
        lines.append(f"- #{issue['number']}: {issue['title']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post audit trail comments on PRs",
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--mapping",
        required=True,
        help="Path to JSON mapping file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show comments without posting",
    )
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    if not mapping_path.is_file():
        print(f"Mapping file not found: {mapping_path}", file=sys.stderr)
        return 1

    try:
        mapping = json.loads(mapping_path.read_text())
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {mapping_path}: {e}", file=sys.stderr)
        return 1
    posted = 0
    failed = 0

    for entry in mapping:
        pr_number = entry["pr_number"]
        issues = entry.get("issues", [])
        if not issues:
            continue

        body = format_comment(issues=issues)

        if args.dry_run:
            print(f"PR #{pr_number}:")
            print(f"  {body}")
            print()
            posted += 1
            continue

        if post_comment(repo=args.repo, pr_number=pr_number, body=body):
            posted += 1
        else:
            failed += 1

    verb = "Would post" if args.dry_run else "Posted"
    print(f"{verb} audit comments on {posted} PRs.")
    if failed:
        print(f"Failed: {failed} PRs.", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
