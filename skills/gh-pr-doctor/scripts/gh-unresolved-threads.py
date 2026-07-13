#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Scan merged PRs for unresolved review comment threads.

Uses GitHub REST API to list merged PRs and GraphQL to check
thread resolution status. Skips PRs with audit trail markers.

The sweep batches PRs into chunked GraphQL queries via field
aliasing (GH-836): each request resolves up to ``CHUNK_SIZE`` PRs
and folds the audit-marker comment fetch into the same query, so a
200-PR scan costs ~1 REST call + ceil(200/CHUNK_SIZE) GraphQL calls
instead of the previous ~2 gh subprocesses per PR (which timed out
at scale — GH-710 only fixed the single-PR path in the MCP wrapper).

Output: JSON array of PRs with unresolved threads.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator

AUDIT_MARKER = "PR Audit"

# PRs per chunked GraphQL request (GH-836). GitHub caps aliased node
# resolution and query cost; 25 keeps each request well under the
# 500k node-count budget while cutting subprocess count ~50×.
CHUNK_SIZE = 25

# Per-PR field selection, reused for every alias in a chunk. Pulls the
# review threads AND the conversation comments (for the audit marker)
# in one shot so no separate ``gh pr view`` call is needed per PR.
# ``comments(first: 100)`` is GraphQL's per-connection max; a PR whose
# audit marker only appears past its first 100 conversation comments is
# re-scanned rather than skipped — an accepted trade-off for dropping the
# per-PR ``gh pr view`` round-trip (GH-836).
_PR_FIELDS = """
    number
    title
    comments(first: 100) { nodes { body } }
    reviewThreads(first: 100) {
      nodes {
        isResolved
        comments(first: 1) {
          nodes {
            body
            author { login }
            path
          }
        }
      }
    }
"""


def run_gh(args: list[str]) -> str:
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"gh error: {result.stderr.strip()}", file=sys.stderr)
        return ""
    return result.stdout.strip()


def fetch_merged_prs(
    repo: str,
    limit: int,
) -> list[dict]:
    output = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--limit",
            str(limit),
            "--json",
            "number,title,mergedAt",
        ]
    )
    if not output:
        return []
    return json.loads(output)


def _chunked(items: list[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _build_chunk_query(pr_numbers: list[int]) -> str:
    """Assemble one GraphQL query aliasing every PR in the chunk.

    PR numbers come from our own ``gh pr list`` output and are coerced
    to ``int``, so embedding them directly in the query is injection-safe
    and avoids declaring one ``$prN`` variable per alias.
    """
    aliases = "\n".join(
        f"    pr{index}: pullRequest(number: {int(number)}) {{{_PR_FIELDS}    }}"
        for index, number in enumerate(pr_numbers)
    )
    return (
        "query($owner: String!, $repo: String!) {\n"
        "  repository(owner: $owner, name: $repo) {\n"
        f"{aliases}\n"
        "  }\n"
        "}\n"
    )


def fetch_chunk(
    owner: str,
    repo_name: str,
    pr_numbers: list[int],
) -> dict:
    """Resolve one chunk of PRs; returns the ``repository`` object.

    Keys are the ``pr0``..``prN`` aliases (a null value means the PR
    could not be resolved). Returns an empty dict on gh/JSON failure.
    """
    output = run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={_build_chunk_query(pr_numbers)}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo_name}",
        ]
    )
    if not output:
        return {}
    data = json.loads(output)
    return data.get("data", {}).get("repository", {}) or {}


def _has_audit_marker(pr_node: dict) -> bool:
    comments = pr_node.get("comments", {}).get("nodes", [])
    return any(AUDIT_MARKER in (comment.get("body") or "") for comment in comments)


def _extract_unresolved(pr_node: dict) -> list[dict]:
    threads = pr_node.get("reviewThreads", {}).get("nodes", [])
    unresolved = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = thread.get("comments", {}).get("nodes", [])
        if not comments:
            continue
        comment = comments[0]
        unresolved.append(
            {
                "path": comment.get("path", ""),
                "body": comment.get("body", "")[:200],
                "author": comment.get("author", {}).get("login", "unknown"),
            }
        )
    return unresolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan merged PRs for unresolved review threads",
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max PRs to scan (default: 200)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show findings without side effects",
    )
    args = parser.parse_args()

    owner, repo_name = args.repo.split("/", 1)
    prs = fetch_merged_prs(repo=args.repo, limit=args.limit)

    if not prs:
        print("No merged PRs found.")
        return 0

    print(f"Scanning {len(prs)} merged PRs...", file=sys.stderr)

    findings = []
    clean_count = 0
    skipped_count = 0
    failed_count = 0

    pr_numbers = [pr["number"] for pr in prs]
    titles = {pr["number"]: pr["title"] for pr in prs}

    for chunk in _chunked(pr_numbers, CHUNK_SIZE):
        repo_data = fetch_chunk(owner=owner, repo_name=repo_name, pr_numbers=chunk)
        for index, pr_number in enumerate(chunk):
            pr_node = repo_data.get(f"pr{index}")
            if not pr_node:
                # A failed chunk (fetch_chunk returned {}) or an
                # unresolved alias drops the PR here. Count it instead
                # of silently vanishing it — otherwise a mid-scan API
                # hiccup would erase up to CHUNK_SIZE PRs from every
                # counter and still exit 0 (GH-836 review).
                failed_count += 1
                continue

            if _has_audit_marker(pr_node):
                skipped_count += 1
                continue

            threads = _extract_unresolved(pr_node)
            if threads:
                findings.append(
                    {
                        "pr_number": pr_number,
                        "title": pr_node.get("title") or titles.get(pr_number, ""),
                        "threads": threads,
                    }
                )
            else:
                clean_count += 1

    print(
        f"Results: {len(findings)} PRs with findings, "
        f"{clean_count} clean, {skipped_count} skipped (already audited), "
        f"{failed_count} unscanned (fetch failure)",
        file=sys.stderr,
    )

    print(json.dumps(findings, indent=2))
    # A partial-failure sweep must not read as a clean pass — a non-zero
    # exit distinguishes it for shell callers (GH-836 review).
    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
