#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["slack_sdk"]
# ///
"""
PR notification helper for Phase 3 of pr:monitor.

Consolidates all Phase 3 operations into two subcommands so the entire
phase can be pre-approved as a single Bash allow rule.

Subcommands:
    prepare   — Fetch PR info, count open threads, format Slack message,
                output JSON for Claude to present to user for confirmation.
    send      — Post Slack notification, assign GitHub reviewers, update PR
                body checklist, and save state snapshot.
    status    — Show CI check status table, unhandled review comments, and
                assigned reviewers with their review status.

Usage:
    pr-notify.py prepare --pr 123 --repo owner/repo
    pr-notify.py send --pr 123 --repo owner/repo \\
        --channel CHANNEL_ID --message-file /tmp/Dev10x/pr-monitor/pr-notify-msg.txt \\
        --reviewer org/team \\
        [--skip-slack] [--skip-reviewers] [--skip-checklist]
    pr-notify.py status --pr 123 --repo owner/repo [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import ErrorResult
from dev10x.skills.common.jtbd import extract_jtbd, md_to_slack_bold
from dev10x.skills.notifications import slack_notify


def gh_json(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"[ERROR] gh {' '.join(args)}: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def gh_run(args: list[str]) -> None:
    result = subprocess.run(["gh", *args], timeout=30)
    if result.returncode != 0:
        print(f"[ERROR] gh {' '.join(args)} failed", file=sys.stderr)
        sys.exit(1)


def count_open_threads(pr_number: int, repo: str) -> int:
    count = gh_json(
        args=[
            "api",
            f"repos/{repo}/pulls/{pr_number}/comments",
            "--jq",
            "[.[] | select(.in_reply_to_id == null)] | length",
        ]
    )
    return int(count)


def split_title_jtbd(pr_title: str) -> tuple[str, str | None]:
    if " \u2014 " in pr_title:
        title, embedded_jtbd = pr_title.split(" \u2014 ", maxsplit=1)
        return title.strip(), embedded_jtbd.strip()
    return pr_title, None


def _repo_name(repo: str) -> str:
    ref = RepositoryRef.try_parse(repo)
    if ref is not None:
        return ref.name
    return repo.split("/")[-1]


def format_slack_message(
    pr_number: int,
    repo: str,
    pr_url: str,
    pr_title: str,
    jtbd: str | None,
) -> str:
    repo_short = _repo_name(repo)
    link = f"<{pr_url}|{repo_short}#{pr_number}>"
    short_title, title_jtbd = split_title_jtbd(pr_title=pr_title)
    effective_jtbd = jtbd or title_jtbd
    lines = [f"Please review {link}", short_title]
    if effective_jtbd:
        lines.append(f"> {md_to_slack_bold(effective_jtbd)}")
    return "\n".join(lines)


def update_pr_checklist(pr_number: int, repo: str, diff: str) -> None:
    pr = gh_json(args=["pr", "view", str(pr_number), "--repo", repo, "--json", "body"])
    body: str = pr.get("body") or ""

    has_migrations = "migrations/" in diff
    has_env_changes = "settings" in diff and ("='" in diff or '="' in diff)
    has_breaking = False  # Conservative default

    replacements = [
        ("- [ ] CI is passing", "- [x] CI is passing"),
        (
            "- [ ] A person or better yet a group is selected in the reviewers section",
            "- [x] A person or better yet a group is selected in the reviewers section",
        ),
        (
            "- [ ] Clean history with auto-squashed fixup! commits",
            "- [x] Clean history with auto-squashed fixup! commits",
        ),
    ]

    if not has_migrations:
        replacements.append(
            (
                "- [ ] **Data migrations** are present (if applicable) and unit tested",
                "- ~**Data migrations** are present (if applicable) and unit tested~",
            )
        )

    if not has_env_changes:
        replacements.append(
            (
                "- [ ] **New environment variables** are documented",
                "- ~**New environment variables** are documented~",
            )
        )

    if not has_breaking:
        replacements.append(
            (
                "- [ ] **Breaking changes** are communicated to the team",
                "- ~**Breaking changes** are communicated to the team~",
            )
        )

    updated = body
    for old, new in replacements:
        updated = updated.replace(old, new)

    if updated == body:
        print("No checklist items found to update.")
        return

    gh_run(args=["pr", "edit", str(pr_number), "--repo", repo, "--body", updated])
    print(f"✅ PR #{pr_number} checklist updated.")


def get_ci_checks(pr_number: int, repo: str) -> list[dict[str, Any]]:
    # `gh pr checks --json` no longer accepts `conclusion` (GH-773); the
    # normalized outcome now lives in `bucket`
    # (pass/fail/pending/skipping/cancel).
    return gh_json(
        args=[
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "name,bucket,startedAt,completedAt",
        ]
    )


def get_review_comments(pr_number: int, repo: str) -> list[dict[str, Any]]:
    return gh_json(
        args=[
            "api",
            f"repos/{repo}/pulls/{pr_number}/comments",
            "--jq",
            "[.[] | select(.in_reply_to_id == null)"
            " | {id, user: .user.login, path, line:"
            " .original_line, body: .body[:80],"
            ' resolved: (.subject_type == "line" and'
            " .position == null)}]",
        ]
    )


def get_reviewers(pr_number: int, repo: str) -> dict[str, Any]:
    return gh_json(
        args=[
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "reviewRequests,reviews,latestReviews",
        ]
    )


def format_ci_table(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "No CI checks found."
    lines = ["| Check | Status | Duration |", "| --- | --- | --- |"]
    icons = {
        "pass": "✅",
        "fail": "❌",
        "pending": "⏳",
        "skipping": "⏭️",
        "cancel": "🚫",
    }
    for c in checks:
        name = c.get("name", "unknown")
        bucket = c.get("bucket", "")
        icon = icons.get(bucket, "⏸️")
        status = f"{icon} {bucket or 'unknown'}"
        started = c.get("startedAt") or ""
        completed = c.get("completedAt") or ""
        if started and completed:
            t0 = datetime.fromisoformat(started)
            t1 = datetime.fromisoformat(completed)
            secs = int((t1 - t0).total_seconds())
            duration = f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"
        elif bucket == "pending":
            duration = "..."
        else:
            duration = "-"
        lines.append(f"| {name} | {status} | {duration} |")
    return "\n".join(lines)


def format_comments_section(
    comments: list[dict[str, Any]],
) -> str:
    unresolved = [c for c in comments if not c.get("resolved")]
    if not unresolved:
        return "No unhandled review comments."
    lines = [f"**{len(unresolved)} unhandled comment(s):**\n"]
    for c in unresolved:
        user = c.get("user", "?")
        path = c.get("path", "?")
        line_no = c.get("line", "?")
        body = c.get("body", "").split("\n")[0][:60]
        lines.append(f"- **{user}** on `{path}:{line_no}` — {body}")
    return "\n".join(lines)


def format_reviewers_section(data: dict[str, Any]) -> str:
    lines: list[str] = []
    requests = data.get("reviewRequests", [])
    latest = data.get("latestReviews", [])
    if not requests and not latest:
        return "No reviewers assigned."
    review_map: dict[str, str] = {}
    for r in latest:
        login = r.get("author", {}).get("login", "?")
        state = r.get("state", "PENDING")
        icon = {
            "APPROVED": "✅",
            "CHANGES_REQUESTED": "🔄",
            "COMMENTED": "💬",
            "DISMISSED": "⚪",
        }.get(state, "⏳")
        review_map[login] = f"{icon} {state.lower()}"
    for req in requests:
        login = req.get("login") or req.get("name", "?")
        if login not in review_map:
            review_map[login] = "⏳ requested"
    lines.append("| Reviewer | Status |")
    lines.append("| --- | --- |")
    for login, status in review_map.items():
        lines.append(f"| @{login} | {status} |")
    return "\n".join(lines)


def format_status_report(
    checks: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    reviewers: dict[str, Any],
) -> str:
    sections = [
        "## CI Check Status\n",
        format_ci_table(checks=checks),
        "\n## Review Comments\n",
        format_comments_section(comments=comments),
        "\n## Reviewers\n",
        format_reviewers_section(data=reviewers),
    ]
    return "\n".join(sections)


def cmd_status(args: argparse.Namespace) -> None:
    checks = get_ci_checks(pr_number=args.pr, repo=args.repo)
    comments = get_review_comments(pr_number=args.pr, repo=args.repo)
    reviewers = get_reviewers(pr_number=args.pr, repo=args.repo)
    report = format_status_report(checks=checks, comments=comments, reviewers=reviewers)
    if args.json:
        output = {
            "ci_checks": checks,
            "review_comments": comments,
            "reviewers": reviewers,
            "report_markdown": report,
        }
        print(json.dumps(output, indent=2))
    else:
        print(report)


def cmd_prepare(args: argparse.Namespace) -> None:
    pr = gh_json(
        args=[
            "pr",
            "view",
            str(args.pr),
            "--repo",
            args.repo,
            "--json",
            "number,title,body,url,state",
        ]
    )

    open_threads = count_open_threads(pr_number=args.pr, repo=args.repo)
    jtbd = extract_jtbd(body=pr.get("body") or "")
    message = format_slack_message(
        pr_number=args.pr,
        repo=args.repo,
        pr_url=pr["url"],
        pr_title=pr["title"],
        jtbd=jtbd,
    )

    output = {
        "pr_number": args.pr,
        "repo": args.repo,
        "pr_url": pr["url"],
        "pr_title": pr["title"],
        "pr_state": pr["state"],
        "open_threads": open_threads,
        "jtbd_found": jtbd is not None,
        "jtbd": jtbd,
        "slack_message": message,
        "ready": open_threads == 0 and pr["state"] == "OPEN",
    }

    print(json.dumps(output, indent=2))


def cmd_send(args: argparse.Namespace) -> None:
    slack_ts: str | None = None

    if not args.skip_slack:
        if not args.message_file and not args.message:
            print("❌ --message or --message-file required", file=sys.stderr)
            sys.exit(1)

        message = args.message
        if args.message_file:
            message = Path(args.message_file).read_text()

        # Post via importable slack_notify module (GH-442). Works in both
        # plugin-checkout and uvx-installed contexts.
        if args.channel:
            result = slack_notify.notify_slack(channel=args.channel, message=message)
            if isinstance(result, ErrorResult):
                print(f"❌ Slack notification failed: {result.error}", file=sys.stderr)
                sys.exit(1)
            print(f"✅ Slack message sent successfully! ts={result.value}")
            slack_ts = result.value
        else:
            print(f"📋 Notification message (post manually):\n{message}")

    if not args.skip_reviewers and args.reviewer:
        gh_run(
            args=[
                "pr",
                "edit",
                str(args.pr),
                "--repo",
                args.repo,
                "--add-reviewer",
                args.reviewer,
            ]
        )
        print(f"✅ Assigned reviewer: {args.reviewer}")

    if not args.skip_checklist:
        diff_result = subprocess.run(
            ["gh", "pr", "diff", str(args.pr), "--repo", args.repo],
            capture_output=True,
            text=True,
            timeout=60,
        )
        diff = diff_result.stdout if diff_result.returncode == 0 else ""
        update_pr_checklist(pr_number=args.pr, repo=args.repo, diff=diff)

    print(f"✅ Phase 3 complete for PR #{args.pr}")
    if slack_ts:
        print(f"   Slack thread_ts: {slack_ts}")


def main() -> None:
    parser = argparse.ArgumentParser(description="PR Phase 3 notification helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--pr", type=int, required=True, help="PR number")
        p.add_argument("--repo", required=True, help="GitHub repo (owner/name)")

    p_prepare = subparsers.add_parser(
        "prepare",
        help="Fetch PR info and format message for user confirmation",
    )
    add_common(p=p_prepare)

    p_send = subparsers.add_parser(
        "send",
        help="Post notification, assign reviewers, update checklist",
    )
    add_common(p=p_send)
    p_send.add_argument("--channel", help="Slack channel ID")
    p_send.add_argument("--message", help="Notification message text")
    p_send.add_argument("--message-file", help="Read message from file")
    p_send.add_argument("--reviewer", help="GitHub reviewer to assign (user or org/team)")
    p_send.add_argument(
        "--skip-slack",
        action="store_true",
        help="Skip posting Slack notification",
    )
    p_send.add_argument(
        "--skip-reviewers",
        action="store_true",
        help="Skip assigning GitHub reviewers",
    )
    p_send.add_argument(
        "--skip-checklist",
        action="store_true",
        help="Skip updating PR body checklist",
    )

    p_status = subparsers.add_parser(
        "status",
        help="Show CI checks, review comments, and reviewer status",
    )
    add_common(p=p_status)
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of markdown",
    )

    args = parser.parse_args()
    try:
        args.repo = str(RepositoryRef.parse(args.repo))
    except ValueError as exc:
        parser.error(str(exc))
    commands = {
        "prepare": cmd_prepare,
        "send": cmd_send,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
