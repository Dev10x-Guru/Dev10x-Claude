#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Collect PRs and JTBDs for a release range.

Usage:
    collect-prs.py <repo-path> [--from TAG] [--to TAG] [--ticket-pattern REGEX]

Outputs structured markdown with:
- Release metadata (tags, commit count)
- Feature PRs with existing JTBDs
- Feature PRs missing JTBDs (need generation)
- Maintenance PRs (no JTBD needed)
- Skipped commits (version bumps, reverts)

Data pipeline:
    1. git log between tags → commits
    2. Extract ticket IDs from commit messages
    3. Deduplicate tickets and find merged PRs via gh
    4. Extract JTBDs from PR descriptions
    5. Classify and output structured report
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from dev10x.domain.common.ticket_id import TICKET_ID_PATTERN
from dev10x.skills.common.jtbd import extract_jtbd_structured
from dev10x.skills.release.classifier import (
    SKIP_CATEGORIES,
    classify_group,
    classify_subject,
)

DEFAULT_TICKET_PATTERN = TICKET_ID_PATTERN

# Upper bound on merged PRs fetched in one batch (GH-550). A release
# window rarely exceeds this; the former per-ticket search had no such
# cap but paid one subprocess per ticket.
MERGED_PR_FETCH_LIMIT = 300


@dataclass
class Commit:
    sha: str
    subject: str
    gitmoji: str
    category: str
    ticket_id: str | None
    is_revert: bool


@dataclass
class PRInfo:
    number: int
    title: str
    body: str
    jtbd: str | None
    tickets: list[str] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    category: str = "feature"


def run(
    cmd: list[str],
    cwd: str | None = None,
    check: bool = True,
) -> str:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if check and result.returncode != 0:
        print(f"Error: {' '.join(cmd)} failed with code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_latest_tags(
    repo_path: str,
    count: int = 2,
) -> list[str]:
    output = run(
        ["git", "tag", "--sort=-v:refname"],
        cwd=repo_path,
    )
    tags = [t for t in output.splitlines() if t]
    return tags[:count]


def build_ticket_regex(patterns: list[str]) -> re.Pattern[str]:
    combined = "|".join(f"({p})" for p in patterns)
    return re.compile(combined)


def get_commits_in_range(
    repo_path: str,
    from_tag: str,
    to_tag: str,
    ticket_regex: re.Pattern[str],
) -> list[Commit]:
    output = run(
        [
            "git",
            "log",
            f"{from_tag}..{to_tag}",
            "--no-merges",
            "--format=%H|||%s",
        ],
        cwd=repo_path,
    )
    commits: list[Commit] = []
    for line in output.splitlines():
        if "|||" not in line:
            continue
        sha, subject = line.split("|||", maxsplit=1)

        gitmoji, category = classify_subject(subject=subject)

        ticket_match = ticket_regex.search(subject)
        ticket_id = ticket_match.group(0) if ticket_match else None

        is_revert = subject.lower().startswith("revert ")

        commits.append(
            Commit(
                sha=sha[:8],
                subject=subject,
                gitmoji=gitmoji,
                category=category,
                ticket_id=ticket_id,
                is_revert=is_revert,
            )
        )
    return commits


def find_reverted_shas(commits: list[Commit]) -> set[str]:
    reverted: set[str] = set()
    for c in commits:
        if c.is_revert:
            sha_match = re.search(r"([0-9a-f]{40})", c.subject)
            if sha_match:
                reverted.add(sha_match.group(1)[:8])
            reverted.add(c.sha)
    return reverted


def collect_ticket_groups(
    commits: list[Commit],
    skip_shas: set[str],
) -> dict[str, list[Commit]]:
    groups: dict[str, list[Commit]] = defaultdict(list)
    for c in commits:
        if c.sha in skip_shas:
            continue
        if c.category in SKIP_CATEGORIES:
            continue
        key = c.ticket_id or c.sha
        groups[key].append(c)
    return dict(groups)


def fetch_merged_prs(
    repo_path: str,
    limit: int = MERGED_PR_FETCH_LIMIT,
) -> list[dict]:
    """Fetch all merged PRs in one ``gh`` call (GH-550).

    Replaces the former per-ticket ``gh pr list --search <id>`` loop,
    which spawned one subprocess per release ticket (N+1). Ticket IDs
    are matched against these PRs in-memory by ``find_matching_prs``.
    """
    output = run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--json",
            "number,title,body",
            "--limit",
            str(limit),
        ],
        cwd=repo_path,
        check=False,
    )
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


def find_matching_prs(
    ticket_id: str,
    merged_prs: list[dict],
) -> list[dict]:
    """Return merged PRs whose title or body references ``ticket_id``."""
    pattern = re.compile(rf"\b{re.escape(ticket_id)}\b")
    matches: list[dict] = []
    for pr in merged_prs:
        haystack = f"{pr.get('title', '')}\n{pr.get('body', '')}"
        if pattern.search(haystack):
            matches.append(pr)
    return matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect PRs and JTBDs for a release range",
    )
    parser.add_argument(
        "repo_path",
        help="Path to the git repository",
    )
    parser.add_argument(
        "--from",
        dest="from_tag",
        default=None,
        help="Start tag (default: second-latest tag)",
    )
    parser.add_argument(
        "--to",
        dest="to_tag",
        default=None,
        help="End tag (default: latest tag)",
    )
    parser.add_argument(
        "--ticket-pattern",
        action="append",
        default=None,
        help=(f"Regex pattern for ticket IDs (repeatable). Default: {DEFAULT_TICKET_PATTERN}"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_path: str = args.repo_path
    from_tag: str | None = args.from_tag
    to_tag: str | None = args.to_tag
    ticket_patterns: list[str] = args.ticket_pattern or [DEFAULT_TICKET_PATTERN]

    ticket_regex = build_ticket_regex(patterns=ticket_patterns)

    if not from_tag or not to_tag:
        tags = get_latest_tags(repo_path=repo_path)
        if len(tags) < 2:
            print("Error: Need at least 2 tags", file=sys.stderr)
            sys.exit(1)
        to_tag = to_tag or tags[0]
        from_tag = from_tag or tags[1]

    repo_name = Path(repo_path).name

    commits = get_commits_in_range(
        repo_path=repo_path,
        from_tag=from_tag,
        to_tag=to_tag,
        ticket_regex=ticket_regex,
    )

    reverted_shas = find_reverted_shas(commits=commits)
    ticket_groups = collect_ticket_groups(
        commits=commits,
        skip_shas=reverted_shas,
    )

    skipped = [c for c in commits if c.sha in reverted_shas or c.category in SKIP_CATEGORIES]

    merged_prs = fetch_merged_prs(repo_path=repo_path)

    seen_pr_numbers: dict[int, PRInfo] = {}
    feature_prs: list[PRInfo] = []
    maintenance_prs: list[PRInfo] = []
    no_pr_found: list[tuple[str, list[Commit]]] = []

    for ticket_id, group_commits in ticket_groups.items():
        group_category = classify_group(categories={c.category for c in group_commits})

        pr_list = find_matching_prs(
            ticket_id=ticket_id,
            merged_prs=merged_prs,
        )

        if pr_list:
            for pr_data in pr_list:
                pr_num = pr_data["number"]
                if pr_num in seen_pr_numbers:
                    existing = seen_pr_numbers[pr_num]
                    if ticket_id not in existing.tickets:
                        existing.tickets.append(ticket_id)
                    existing.commits.extend(group_commits)
                    if group_category == "feature" and existing.category != "feature":
                        existing.category = "feature"
                    continue

                jtbd = extract_jtbd_structured(body=pr_data.get("body", ""))
                pr_category = classify_group(categories={c.category for c in group_commits})
                pr_info = PRInfo(
                    number=pr_num,
                    title=pr_data["title"],
                    body=pr_data.get("body", ""),
                    jtbd=jtbd,
                    tickets=[ticket_id],
                    commits=list(group_commits),
                    category=pr_category,
                )
                seen_pr_numbers[pr_num] = pr_info
                if pr_category == "maintenance":
                    maintenance_prs.append(pr_info)
                else:
                    feature_prs.append(pr_info)
        else:
            no_pr_found.append((ticket_id, group_commits))

    print(f"# Release PR Collection: {repo_name} {from_tag}..{to_tag}")
    print()
    print(f"- **Repo**: {repo_name}")
    print(f"- **Range**: {from_tag}..{to_tag}")
    print(f"- **Total commits**: {len(commits)}")
    print(f"- **Skipped** (bumps/reverts): {len(skipped)}")
    print(f"- **Feature PRs**: {len(feature_prs)}")
    print(f"- **Maintenance PRs**: {len(maintenance_prs)}")
    print()

    if feature_prs:
        with_jtbd = [p for p in feature_prs if p.jtbd]
        without_jtbd = [p for p in feature_prs if not p.jtbd]

        if with_jtbd:
            print("## Feature PRs with JTBDs")
            print()
            for pr in with_jtbd:
                print(f"### PR #{pr.number}: {pr.title}")
                print(f"- **Ticket**: {', '.join(pr.tickets)}")
                print(f"- **Category**: {pr.category}")
                print(f"- **JTBD**: {pr.jtbd}")
                print()

        if without_jtbd:
            print("## Feature PRs MISSING JTBDs (need generation)")
            print()
            for pr in without_jtbd:
                print(f"### PR #{pr.number}: {pr.title}")
                print(f"- **Ticket**: {', '.join(pr.tickets)}")
                print(f"- **Category**: {pr.category}")
                first_lines = pr.body[:200] if pr.body else "(empty)"
                print(f"- **Body preview**: {first_lines}")
                print()

    if maintenance_prs:
        print("## Maintenance PRs")
        print()
        for pr in maintenance_prs:
            print(f"- PR #{pr.number}: {pr.title} ({', '.join(pr.tickets)})")
        print()

    if no_pr_found:
        print("## Commits without PRs")
        print()
        for ticket_id, group_commits in no_pr_found:
            subjects = "; ".join(c.subject for c in group_commits)
            print(f"- {ticket_id}: {subjects}")
        print()

    if skipped:
        print("## Skipped commits")
        print()
        for c in skipped:
            reason = "revert" if c.is_revert else c.category
            print(f"- {c.sha} {c.subject} ({reason})")


if __name__ == "__main__":
    main()
