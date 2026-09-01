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
from dev10x.skills.notifications import gchat_cards
from dev10x.skills.notifications._gh import (  # noqa: F401  (GhCommandError re-exported for the CLI except)
    GhCommandError,
    gh_json,
)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def _resolution(
    *,
    skip: bool = False,
    ask: bool = False,
    space: str | None = None,
    mentions: list[str] | None = None,
    card: bool = False,
) -> dict[str, Any]:
    """Every branch of ``resolve_project_config`` returns this one shape.

    Built through a single constructor so a key added for one branch — as
    ``card`` was — cannot be missed on the others.
    """
    return {
        "skip": skip,
        "ask": ask,
        "space": space,
        "mentions": mentions if mentions is not None else [],
        "card": card,
    }


def resolve_project_config(config: dict, repo_name: str) -> dict[str, Any]:
    projects = config.get("projects", {})
    default_action = config.get("default_action", "ask")

    if repo_name in projects:
        entry = projects[repo_name]
        if entry.get("skip", False):
            return _resolution(skip=True)
        return _resolution(
            space=entry.get("space"),
            mentions=entry.get("mentions", []),
            card=entry.get("card", config.get("default_card", False)),
        )

    if default_action == "skip":
        return _resolution(skip=True)

    return _resolution(ask=True)


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


def format_review_card(
    pr_number: int,
    repo: str,
    pr_url: str,
    pr_title: str,
    jtbd: str | None,
) -> dict[str, Any]:
    """Render the review request as a cardsV2 panel (GH-1113).

    Mentions are deliberately absent — a card does not resolve
    ``<users/ID>`` tokens, so they ride in the message's ``text`` field
    that accompanies this card.
    """
    widgets: list[dict[str, Any]] = []
    if jtbd:
        widgets.append(gchat_cards.text_paragraph(jtbd))
    widgets.append(gchat_cards.button_list([gchat_cards.link_button(text="Open PR", url=pr_url)]))
    return gchat_cards.card(
        card_id=f"review-{_repo_name(repo)}-{pr_number}",
        title=pr_title,
        subtitle=f"{_repo_name(repo)}#{pr_number}",
        sections=[gchat_cards.section(widgets=widgets)],
    )


def format_card_notice(resolved_mentions: list[str]) -> str:
    """The plain-text half of a card message — carries the mentions."""
    mentions_prefix = f"{' '.join(resolved_mentions)} " if resolved_mentions else ""
    return f"{mentions_prefix}Please review"


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

    envelope: dict[str, Any] = {
        "skip": False,
        "ask": False,
        "space": project["space"],
        "mentions": project["mentions"],
        "resolved_mentions": resolved_mentions,
        "message": message,
        "pr_url": pr["url"],
        "pr_title": pr["title"],
        "card": None,
        "fallback_text": None,
    }
    if project["card"]:
        envelope["card"] = format_review_card(
            pr_number=args.pr,
            repo=args.repo,
            pr_url=pr["url"],
            pr_title=pr["title"],
            jtbd=jtbd,
        )
        envelope["fallback_text"] = gchat_cards.plain_text_fallback(message)
        # Mentions cannot notify from inside a card, so the text half keeps them.
        envelope["message"] = format_card_notice(resolved_mentions=resolved_mentions)

    print(json.dumps(envelope, indent=2))
