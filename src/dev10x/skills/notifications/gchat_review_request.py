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
    card: bool = True,
    preview: bool = False,
    preview_environment: str | None = None,
) -> dict[str, Any]:
    """Every branch of ``resolve_project_config`` returns this one shape.

    Built through a single constructor so a key added for one branch — as
    ``card`` was — cannot be missed on the others. ``card`` defaults on
    (GH-1115): a repo that says nothing about cards gets a panel, and both
    opt-out levers (per-repo ``card: false``, global ``default_card:
    false``) still win.

    ``preview`` defaults OFF, unlike ``card`` (GH-1262): resolving a
    preview URL costs an API round trip per review request, and most repos
    deploy nothing to look at. Opt in per repo.
    """
    return {
        "skip": skip,
        "ask": ask,
        "space": space,
        "mentions": mentions if mentions is not None else [],
        "card": card,
        "preview": preview,
        "preview_environment": preview_environment,
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
            card=entry.get("card", config.get("default_card", True)),
            preview=entry.get("preview", config.get("default_preview", False)),
            preview_environment=entry.get("preview_environment"),
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


# One page is plenty: a PR head SHA accumulates a handful of deployments,
# and an unbounded walk would cost a status call each on a path that must
# never delay the ping.
_DEPLOYMENT_PAGE_SIZE = 10

# `<url|label>` is Chat's link syntax, so a URL carrying `|`, `<` or `>`
# rewrites the link around it.
_CHAT_LINK_DELIMITERS = ("|", "<", ">")


def _is_safe_preview_url(value: Any) -> bool:
    """Whether a deployment's URL is safe to render as a click target.

    `environment_url` is written by whoever created the deployment status
    — a provider's bot, or any workflow holding `deployments: write`. Some
    preview actions build it from branch or PR text, so it is third-party
    input, not something this code generated. It becomes a button's
    `openLink` and a Chat link, neither of which validates a scheme, so a
    `javascript:` or `data:` value would be handed to the reviewer as a
    thing to click.
    """
    if not isinstance(value, str):
        return False
    if not value.startswith(("https://", "http://")):
        return False
    return not any(delimiter in value for delimiter in _CHAT_LINK_DELIMITERS)


def resolve_preview_url(
    *,
    repo: str,
    head_sha: str,
    environment: str | None = None,
) -> str | None:
    """The deployed URL for ``head_sha``, or ``None`` when there isn't one.

    Read from the Deployments API rather than a bot comment, because
    ``deployment_status.environment_url`` is the one field Vercel, Netlify
    and Pages all populate, and a comment's wording is the provider's to
    change without notice.

    Returns ``None`` for every unhappy path — no deployments, none
    succeeded yet, the API refused, the response was not shaped as
    expected. A review request that arrives late is worse than one missing
    a button, so nothing here is allowed to raise or retry (GH-1262).
    """
    try:
        deployments = gh_json(
            args=[
                "api",
                f"repos/{repo}/deployments?sha={head_sha}&per_page={_DEPLOYMENT_PAGE_SIZE}",
            ]
        )
    except (GhCommandError, json.JSONDecodeError):
        return None

    if not isinstance(deployments, list):
        return None

    for deployment in deployments:
        if not isinstance(deployment, dict):
            continue
        if environment is not None and deployment.get("environment") != environment:
            continue
        url = _successful_environment_url(repo=repo, deployment_id=deployment.get("id"))
        if url:
            return url
    return None


def _successful_environment_url(*, repo: str, deployment_id: Any) -> str | None:
    if deployment_id is None:
        return None
    try:
        statuses = gh_json(args=["api", f"repos/{repo}/deployments/{deployment_id}/statuses"])
    except (GhCommandError, json.JSONDecodeError):
        return None

    if not isinstance(statuses, list):
        return None

    # Statuses come back newest first. A still-running deployment reports
    # `queued`/`in_progress` above its predecessor, so those are skipped —
    # but a terminal non-success is the deployment's current verdict, and
    # reading past it would link to a build that has since been replaced
    # or torn down.
    for status in statuses:
        if not isinstance(status, dict):
            continue
        state = status.get("state")
        if state in ("queued", "pending", "in_progress"):
            continue
        if state != "success":
            return None
        url = status.get("environment_url")
        return url if _is_safe_preview_url(url) else None
    return None


def format_review_message(
    pr_number: int,
    repo: str,
    pr_url: str,
    pr_title: str,
    jtbd: str | None,
    resolved_mentions: list[str],
    preview_url: str | None = None,
) -> str:
    repo_short = _repo_name(repo)
    link = f"<{pr_url}|{repo_short}#{pr_number}>"
    mentions_prefix = f"{' '.join(resolved_mentions)} " if resolved_mentions else ""
    lines = [f"{mentions_prefix}Please review {link}", f"*{pr_title}*"]
    if jtbd:
        lines.append(f"> {md_to_slack_bold(jtbd)}")
    # A card-less repo has no buttons, so the preview has to ride the text
    # or the feature does nothing at all for those repos (GH-1262).
    if preview_url:
        lines.append(f"Preview app: <{preview_url}|{preview_url}>")
    return "\n".join(lines)


def format_review_card(
    pr_number: int,
    repo: str,
    pr_url: str,
    pr_title: str,
    jtbd: str | None,
    preview_url: str | None = None,
) -> dict[str, Any]:
    """Render the review request as a cardsV2 panel (GH-1113).

    Mentions are deliberately absent — a card does not resolve
    ``<users/ID>`` tokens, so they ride in the message's ``text`` field
    that accompanies this card.

    The Preview App button appears only when a URL was resolved, so a repo
    with no preview deployment renders the card it rendered before
    GH-1262.
    """
    widgets: list[dict[str, Any]] = []
    if jtbd:
        widgets.append(gchat_cards.text_paragraph(jtbd))
    buttons = [gchat_cards.link_button(text="Open PR", url=pr_url)]
    if preview_url:
        buttons.append(gchat_cards.link_button(text="Preview App", url=preview_url))
    widgets.append(gchat_cards.button_list(buttons))
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
        args=[
            "pr",
            "view",
            str(args.pr),
            "--repo",
            args.repo,
            "--json",
            "number,title,body,url,headRefOid",
        ]
    )

    preview_url = None
    if project["preview"] and pr.get("headRefOid"):
        preview_url = resolve_preview_url(
            repo=args.repo,
            head_sha=pr["headRefOid"],
            environment=project["preview_environment"],
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
        preview_url=preview_url,
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
        "preview_url": preview_url,
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
            preview_url=preview_url,
        )
        envelope["fallback_text"] = gchat_cards.plain_text_fallback(message)
        # Mentions cannot notify from inside a card, so the text half keeps them.
        envelope["message"] = format_card_notice(resolved_mentions=resolved_mentions)

    print(json.dumps(envelope, indent=2))
