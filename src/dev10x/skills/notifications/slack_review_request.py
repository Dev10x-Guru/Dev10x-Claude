#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""
Slack review request — resolve per-project config and post review
notification to Slack.

Subcommands:
    prepare  — Resolve project config, format message, output JSON.
    send     — Post message via slack-notify.py.

Config: Dev10xConfigDir.slack_review_config_yaml()
Slack config: Dev10xConfigDir.slack_config_yaml()
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.common.jtbd import extract_jtbd, md_to_slack_bold


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def resolve_project_config(
    config: dict,
    repo_name: str,
) -> dict[str, Any]:
    projects = config.get("projects", {})
    default_action = config.get("default_action", "ask")

    if repo_name in projects:
        entry = projects[repo_name]
        if entry.get("skip", False):
            return {"skip": True, "ask": False, "channel": None, "mentions": []}
        return {
            "skip": False,
            "ask": False,
            "channel": entry.get("channel"),
            "mentions": entry.get("mentions", []),
        }

    if default_action == "skip":
        return {"skip": True, "ask": False, "channel": None, "mentions": []}

    return {"skip": False, "ask": True, "channel": None, "mentions": []}


def resolve_mention(
    mention: str,
    slack_config: dict,
) -> str:
    user_groups = slack_config.get("user_groups", {})
    if mention in user_groups:
        return user_groups[mention]

    users = slack_config.get("users", {})
    name = mention.lstrip("@")
    if name in users:
        return f"<@{users[name]['slack_id']}>"

    return mention


def _repo_name(repo: str) -> str:
    return repo.split("/")[-1]


def format_review_message(
    pr_number: int,
    repo: str,
    pr_url: str,
    pr_title: str,
    jtbd: str | None,
    resolved_mentions: list[str],
) -> str:
    repo_short = _repo_name(repo)
    link = f"<{pr_url}|{repo_short}#{pr_number}>"
    mentions_prefix = f"{' '.join(resolved_mentions)} " if resolved_mentions else ""
    lines = [f"{mentions_prefix}Please review {link}", pr_title]
    if jtbd:
        lines.append(f"> {md_to_slack_bold(jtbd)}")
    return "\n".join(lines)


class GhCommandError(RuntimeError):
    """A `gh` invocation failed — raised so entry points own exit codes."""


def gh_json(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise GhCommandError(f"gh {' '.join(args)}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def cmd_prepare(args: argparse.Namespace) -> None:
    config = load_yaml(path=Dev10xConfigDir.slack_review_config_yaml())
    slack_config = load_yaml(path=Dev10xConfigDir.slack_config_yaml())
    repo_name = _repo_name(args.repo)

    project = resolve_project_config(config=config, repo_name=repo_name)

    if project["skip"]:
        print(
            json.dumps(
                {
                    "skip": True,
                    "reason": f"Project '{repo_name}' configured to skip Slack notifications",
                },
                indent=2,
            )
        )
        return

    if project["ask"]:
        print(
            json.dumps(
                {
                    "skip": False,
                    "ask": True,
                    "reason": (
                        f"No config found for '{repo_name}'. "
                        "User should provide channel and mentions."
                    ),
                    "channel": None,
                    "mentions": [],
                    "message": None,
                },
                indent=2,
            )
        )
        return

    pr = gh_json(
        args=[
            "pr",
            "view",
            str(args.pr),
            "--repo",
            args.repo,
            "--json",
            "number,title,body,url",
        ]
    )

    resolved_mentions = [
        resolve_mention(mention=m, slack_config=slack_config) for m in project["mentions"]
    ]

    jtbd = extract_jtbd(body=pr.get("body") or "")

    message = format_review_message(
        pr_number=args.pr,
        repo=args.repo,
        pr_url=pr["url"],
        pr_title=pr["title"],
        jtbd=jtbd,
        resolved_mentions=resolved_mentions,
    )

    print(
        json.dumps(
            {
                "skip": False,
                "ask": False,
                "channel": project["channel"],
                "mentions": project["mentions"],
                "resolved_mentions": resolved_mentions,
                "message": message,
                "pr_url": pr["url"],
                "pr_title": pr["title"],
            },
            indent=2,
        )
    )


def cmd_send(args: argparse.Namespace) -> None:
    message = args.message
    if args.message_file:
        message = Path(args.message_file).read_text()

    if not message:
        print("❌ --message or --message-file required", file=sys.stderr)
        sys.exit(1)

    slack_notify = Path(__file__).parents[4] / "skills" / "slack" / "slack-notify.py"
    if not slack_notify.exists():
        print(f"❌ slack-notify.py not found at {slack_notify}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [str(slack_notify), "--channel", args.channel, "--message", message],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        print(f"❌ Slack notification failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Slack review request helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--pr", type=int, required=True, help="PR number")
        p.add_argument("--repo", required=True, help="GitHub repo (owner/name)")

    p_prepare = subparsers.add_parser("prepare", help="Resolve config and format message")
    add_common(p=p_prepare)

    p_send = subparsers.add_parser("send", help="Post Slack notification")
    p_send.add_argument("--channel", required=True, help="Slack channel ID")
    p_send.add_argument("--message", help="Message text")
    p_send.add_argument("--message-file", help="Read message from file")

    parsed = parser.parse_args()
    commands = {"prepare": cmd_prepare, "send": cmd_send}
    try:
        commands[parsed.command](parsed)
    except GhCommandError as ex:
        print(f"[ERROR] {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
