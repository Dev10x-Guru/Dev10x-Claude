from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

import pytest

from dev10x.comm.chatbus.approval_dm import ChatApprovalNotifier, approval_text
from dev10x.comm.chatbus.sources.google_http import CHAT_API
from tests.comm.chatbus.factories import expect_error, unwrap
from tests.comm.chatbus.sources.test_google_http import FakeOpener, client, http_error

OWNER = "users/1"
REQUESTER = "users/2"
DM = "spaces/DM1"
MESSAGE = f"{DM}/messages/m1"
FIND_URL = f"{CHAT_API}/spaces:findDirectMessage?" + urllib.parse.urlencode({"name": OWNER})
SETUP_URL = f"{CHAT_API}/spaces:setup"
POST_URL = f"{CHAT_API}/{DM}/messages"


def _notifier(*answers: Any) -> tuple[ChatApprovalNotifier, FakeOpener]:
    json_client, opener = client(*answers)
    return ChatApprovalNotifier(client=json_client), opener


def _request(notifier: ChatApprovalNotifier, *, owner: str = OWNER) -> Any:
    return notifier.request_approval(
        owner=owner, work_item_id=7, requester=REQUESTER, verb="start"
    )


def _calls(opener: FakeOpener) -> list[tuple[str, str]]:
    return [(request.get_method(), request.full_url) for request in opener.requests]


def _payload(opener: FakeOpener, *, index: int) -> Any:
    return json.loads(opener.requests[index].data or b"")


class TestApprovalText:
    def test_names_the_item_the_requester_and_the_verb(self) -> None:
        assert approval_text(work_item_id=7, requester=REQUESTER, verb="start") == (
            "Approval needed for work item 7: `users/2` asked to `start`.\n"
            "React ✅ to this message, or reply `approve 7`, to let it run. "
            "Nothing runs until you do."
        )

    def test_backticks_cannot_break_out_of_the_code_span(self) -> None:
        text = approval_text(work_item_id=7, requester="users/`2", verb="st`art")
        assert "`users/'2`" in text and "`st'art`" in text


class TestRequestApproval:
    def test_posts_into_the_existing_dm_and_returns_the_message_name(self) -> None:
        notifier, opener = _notifier(json.dumps({"name": DM}), json.dumps({"name": MESSAGE}))
        assert unwrap(_request(notifier)) == MESSAGE
        assert _calls(opener) == [("GET", FIND_URL), ("POST", POST_URL)]
        assert _payload(opener, index=1) == {
            "text": approval_text(work_item_id=7, requester=REQUESTER, verb="start")
        }

    def test_sends_with_the_bot_token(self) -> None:
        notifier, opener = _notifier(json.dumps({"name": DM}), json.dumps({"name": MESSAGE}))
        _request(notifier)
        assert opener.requests[1].get_header("Authorization") == "Bearer tok"

    def test_sets_up_the_dm_when_none_exists(self) -> None:
        notifier, opener = _notifier(
            http_error(code=404), json.dumps({"name": DM}), json.dumps({"name": MESSAGE})
        )
        assert unwrap(_request(notifier)) == MESSAGE
        assert _calls(opener) == [("GET", FIND_URL), ("POST", SETUP_URL), ("POST", POST_URL)]
        assert _payload(opener, index=1) == {
            "space": {"spaceType": "DIRECT_MESSAGE", "singleUserBotDm": True},
            "memberships": [{"member": {"name": OWNER, "type": "HUMAN"}}],
        }

    def test_a_failed_lookup_other_than_not_found_sends_nothing(self) -> None:
        notifier, opener = _notifier(http_error(code=403))
        assert "HTTP 403" in expect_error(_request(notifier)).error
        assert _calls(opener) == [("GET", FIND_URL)]

    def test_a_failed_setup_sends_nothing(self) -> None:
        notifier, opener = _notifier(http_error(code=404), http_error(code=403))
        assert "HTTP 403" in expect_error(_request(notifier)).error
        assert _calls(opener) == [("GET", FIND_URL), ("POST", SETUP_URL)]

    @pytest.mark.parametrize("body", [{}, {"name": "rooms/DM1"}])
    def test_a_lookup_without_a_space_name_sends_nothing(self, body: dict[str, str]) -> None:
        notifier, opener = _notifier(json.dumps(body))
        assert "findDirectMessage returned no space name" in expect_error(_request(notifier)).error
        assert len(opener.requests) == 1

    def test_a_setup_without_a_space_name_sends_nothing(self) -> None:
        notifier, opener = _notifier(http_error(code=404), "{}")
        assert "spaces:setup returned no space name" in expect_error(_request(notifier)).error
        assert len(opener.requests) == 2

    def test_a_failed_post_is_an_error(self) -> None:
        notifier, _ = _notifier(json.dumps({"name": DM}), http_error(code=400))
        assert "HTTP 400" in expect_error(_request(notifier)).error

    @pytest.mark.parametrize("body", [{}, {"name": "spaces/OTHER/messages/m1"}])
    def test_a_post_without_a_message_in_the_dm_is_an_error(self, body: dict[str, str]) -> None:
        notifier, _ = _notifier(json.dumps({"name": DM}), json.dumps(body))
        error = expect_error(_request(notifier))
        assert (error.error, error.details) == (
            "Chat returned no message name for the approval DM of work item 7",
            {"work_item_id": 7},
        )

    def test_refuses_an_owner_that_is_not_a_user_name(self) -> None:
        notifier, opener = _notifier()
        assert "users/<id>" in expect_error(_request(notifier, owner="alice")).error
        assert opener.requests == []

    def test_logs_the_sent_dm(self, caplog: pytest.LogCaptureFixture) -> None:
        notifier, _ = _notifier(json.dumps({"name": DM}), json.dumps({"name": MESSAGE}))
        with caplog.at_level(logging.INFO, logger="dev10x.comm.chatbus.approval_dm"):
            _request(notifier)
        assert caplog.messages == [f"Approval DM for work item 7 sent to {OWNER} as {MESSAGE}"]
