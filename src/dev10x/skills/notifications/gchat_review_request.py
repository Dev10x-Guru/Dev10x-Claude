"""Google Chat review request — resolve per-repo config and format the
review notification. Mirrors slack_review_request.py (space where Slack
uses channel). The `send` path delegates to the Dev10x:gchat skill, so
this module only implements `prepare`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.skills.common.jtbd import extract_jtbd, md_to_slack_bold
from dev10x.skills.notifications._gh import (  # noqa: F401  (GhCommandError re-exported for the CLI except)
    GhCommandError,
    gh_json,
)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def resolve_project_config(config: dict, repo_name: str) -> dict[str, Any]:
    projects = config.get("projects", {})
    default_action = config.get("default_action", "ask")

    if repo_name in projects:
        entry = projects[repo_name]
        if entry.get("skip", False):
            return {"skip": True, "ask": False, "space": None, "mentions": []}
        return {
            "skip": False,
            "ask": False,
            "space": entry.get("space"),
            "mentions": entry.get("mentions", []),
        }

    if default_action == "skip":
        return {"skip": True, "ask": False, "space": None, "mentions": []}

    return {"skip": False, "ask": True, "space": None, "mentions": []}


def resolve_mention(mention: str, gchat_config: dict) -> str:
    user_groups = gchat_config.get("user_groups", {})
    if mention in user_groups:
        return user_groups[mention]

    users = gchat_config.get("users", {})
    name = mention.lstrip("@")
    if name in users:
        return f"<users/{users[name]['chat_user_id']}>"

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
    lines = [f"{mentions_prefix}Please review {link}", f"*{pr_title}*"]
    if jtbd:
        lines.append(f"> {md_to_slack_bold(jtbd)}")
    return "\n".join(lines)


def cmd_prepare(args: argparse.Namespace) -> None:
    config = load_yaml(path=Dev10xConfigDir.gchat_review_config_yaml())
    gchat_config = load_yaml(path=Dev10xConfigDir.gchat_config_yaml())
    repo_name = _repo_name(args.repo)

    project = resolve_project_config(config=config, repo_name=repo_name)

    if project["skip"]:
        print(
            json.dumps(
                {
                    "skip": True,
                    "reason": (
                        f"Project '{repo_name}' configured to skip Google Chat notifications"
                    ),
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
                        "User should provide space and mentions."
                    ),
                    "space": None,
                    "mentions": [],
                    "message": None,
                },
                indent=2,
            )
        )
        return

    pr = gh_json(
        args=["pr", "view", str(args.pr), "--repo", args.repo, "--json", "number,title,body,url"]
    )

    resolved_mentions = [
        resolve_mention(mention=m, gchat_config=gchat_config) for m in project["mentions"]
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
                "space": project["space"],
                "mentions": project["mentions"],
                "resolved_mentions": resolved_mentions,
                "message": message,
                "pr_url": pr["url"],
                "pr_title": pr["title"],
            },
            indent=2,
        )
    )
