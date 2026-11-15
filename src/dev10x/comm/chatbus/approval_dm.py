"""Send the owner's approval DM through Google Chat as the bot (ADR-0035 D2, GH-1932).

The notifier finds the bot's DM with the owner, creating it when none
exists, and posts one message naming the work item, the requester and
the verb. The returned message name is stored in
``approvals.dm_message``, so a later ✅ reaction on that message
approves the item. No chat text is copied into the DM: every value
comes from the authorized verdict, and each one is shown as code.

[Verify] The ``spaces:findDirectMessage`` and ``spaces:setup`` request
shapes follow the published Chat REST reference for app authentication.
They were not exercised against the live API in the session that wrote
this module.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any

from dev10x.comm.chatbus.authz import APPROVE_COMMAND, APPROVE_REACTION
from dev10x.comm.chatbus.sources.google_http import CHAT_API, NOT_FOUND, GoogleJsonClient
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

log = logging.getLogger(__name__)

USER_PREFIX = "users/"
SPACE_PREFIX = "spaces/"


def _code(*, value: str) -> str:
    return "`" + value.replace("`", "'") + "`"


def approval_text(*, work_item_id: int, requester: str, verb: str) -> str:
    return (
        f"Approval needed for work item {work_item_id}: "
        f"{_code(value=requester)} asked to {_code(value=verb)}.\n"
        f"React {APPROVE_REACTION} to this message, or reply "
        f"{_code(value=f'{APPROVE_COMMAND} {work_item_id}')}, to let it run. "
        "Nothing runs until you do."
    )


def _space_name(*, payload: dict[str, Any], action: str) -> Result[str]:
    name = payload.get("name")
    if not isinstance(name, str) or not name.startswith(SPACE_PREFIX):
        return err(f"Chat {action} returned no space name")
    return ok(name)


@dataclass(frozen=True)
class ChatApprovalNotifier:
    """Posts approval requests with the bot's token; the client must hold a chat.bot grant."""

    client: GoogleJsonClient

    def request_approval(
        self,
        *,
        owner: str,
        work_item_id: int,
        requester: str,
        verb: str,
    ) -> Result[str]:
        if not owner.startswith(USER_PREFIX):
            return err(f"The approval owner must be a users/<id> name, got {owner!r}")
        space = self._direct_message(owner=owner)
        if isinstance(space, ErrorResult):
            return space
        posted = self.client.request(
            method="POST",
            url=f"{CHAT_API}/{space.value}/messages",
            payload={
                "text": approval_text(work_item_id=work_item_id, requester=requester, verb=verb)
            },
        )
        if isinstance(posted, ErrorResult):
            return posted
        name = posted.value.get("name")
        if not isinstance(name, str) or not name.startswith(f"{space.value}/messages/"):
            return err(
                f"Chat returned no message name for the approval DM of work item {work_item_id}",
                work_item_id=work_item_id,
            )
        log.info("Approval DM for work item %s sent to %s as %s", work_item_id, owner, name)
        return ok(name)

    def _direct_message(self, *, owner: str) -> Result[str]:
        query = urllib.parse.urlencode({"name": owner})
        found = self.client.request(
            method="GET", url=f"{CHAT_API}/spaces:findDirectMessage?{query}"
        )
        if isinstance(found, ErrorResult):
            if found.details.get("status") != NOT_FOUND:
                return found
            return self._set_up(owner=owner)
        return _space_name(payload=found.value, action="findDirectMessage")

    def _set_up(self, *, owner: str) -> Result[str]:
        log.info("No DM between the bot and %s yet; creating one", owner)
        created = self.client.request(
            method="POST",
            url=f"{CHAT_API}/spaces:setup",
            payload={
                "space": {"spaceType": "DIRECT_MESSAGE", "singleUserBotDm": True},
                "memberships": [{"member": {"name": owner, "type": "HUMAN"}}],
            },
        )
        if isinstance(created, ErrorResult):
            return created
        return _space_name(payload=created.value, action="spaces:setup")
