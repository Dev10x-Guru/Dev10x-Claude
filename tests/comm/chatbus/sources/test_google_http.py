from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from typing import Any

import pytest
from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.retry import RetryPolicy

from dev10x.comm.chatbus.sources.google_http import (
    PUBSUB_API,
    WORKSPACE_EVENTS_API,
    GoogleJsonClient,
    PubSubRest,
    WorkspaceEventsRest,
)
from dev10x.comm.chatbus.sources.pubsub import ReceivedMessage, SubscriptionSpec, SubscriptionState
from tests.comm.chatbus.factories import expect_error, unwrap

URL = "https://pubsub.googleapis.com/v1/x"
EXPIRES = "2026-11-06T16:00:00Z"
EXPIRES_AT = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)
SUBSCRIPTION = {"name": "subscriptions/s1", "state": "ACTIVE", "expireTime": EXPIRES}


class FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def http_error(*, code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, "error", headers, io.BytesIO(b"detail"))


@dataclass
class FakeOpener:
    answers: list[Any]
    requests: list[urllib.request.Request] = field(default_factory=list)

    def __call__(self, request: urllib.request.Request, *, timeout: float) -> FakeResponse:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return FakeResponse(answer)


@dataclass
class Sleeps:
    delays: list[float] = field(default_factory=list)

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def token() -> Result[str]:
    return ok("tok")


def client(*answers: Any, sleeps: Sleeps | None = None) -> tuple[GoogleJsonClient, FakeOpener]:
    opener = FakeOpener(answers=list(answers))
    return (
        GoogleJsonClient(
            token=token,
            opener=opener,
            sleep=sleeps or Sleeps(),
            policy=RetryPolicy(attempts=3, jitter=lambda: 1.0),
        ),
        opener,
    )


class TestGoogleJsonClient:
    def test_sends_an_authorized_json_request(self) -> None:
        json_client, opener = client('{"a": 1}')

        result = json_client.request(method="POST", url=URL, payload={"b": 2})

        request = opener.requests[0]
        assert unwrap(result) == {"a": 1}
        assert (request.get_method(), request.data, request.get_header("Authorization")) == (
            "POST",
            b'{"b": 2}',
            "Bearer tok",
        )

    def test_a_get_sends_no_body(self) -> None:
        json_client, opener = client("")

        result = json_client.request(method="GET", url=URL)

        assert (unwrap(result), opener.requests[0].data) == ({}, None)

    def test_backs_off_on_a_throttle_honouring_retry_after(self) -> None:
        sleeps = Sleeps()
        json_client, _ = client(http_error(code=429, retry_after="2"), "{}", sleeps=sleeps)

        result = json_client.request(method="GET", url=URL)

        assert (unwrap(result), sleeps.delays) == ({}, [2.0])

    def test_backs_off_exponentially_on_server_errors(self) -> None:
        sleeps = Sleeps()
        json_client, _ = client(
            http_error(code=503, retry_after="soon"), http_error(code=500), "{}", sleeps=sleeps
        )

        unwrap(json_client.request(method="GET", url=URL))

        assert sleeps.delays == [0.5, 1.0]

    def test_gives_up_after_the_last_attempt(self) -> None:
        reason = urllib.error.URLError("connection refused")
        json_client, opener = client(reason, reason, reason)

        result = json_client.request(method="GET", url=URL)

        assert ("unreachable" in expect_error(result).error, len(opener.requests)) == (True, 3)

    def test_does_not_retry_a_client_error(self) -> None:
        json_client, opener = client(http_error(code=404))

        error = expect_error(json_client.request(method="GET", url=URL))

        assert (error.details, len(opener.requests)) == ({"status": 404}, 1)
        assert "detail" in error.error

    def test_a_non_object_body_reads_as_empty(self) -> None:
        json_client, _ = client("[1]")

        assert unwrap(json_client.request(method="GET", url=URL)) == {}

    def test_an_invalid_body_is_an_error(self) -> None:
        json_client, _ = client("{bad")

        result = json_client.request(method="GET", url=URL)

        assert "invalid JSON" in expect_error(result).error

    def test_a_missing_token_makes_no_request(self) -> None:
        opener = FakeOpener(answers=[])
        json_client = GoogleJsonClient(token=lambda: err("no grant"), opener=opener)

        result = json_client.request(method="GET", url=URL)

        assert (expect_error(result).error, opener.requests) == ("no grant", [])


def _received(data: bytes) -> dict[str, Any]:
    return {
        "ackId": "a1",
        "message": {
            "data": base64.b64encode(data).decode(),
            "attributes": {"ce-type": "t"},
            "publishTime": EXPIRES,
        },
    }


class TestPubSubRest:
    def test_pull_decodes_received_messages(self) -> None:
        body = {
            "receivedMessages": [
                _received(b"{}"),
                {"ackId": "a2", "message": {"data": "!!", "attributes": []}},
                {"message": {}},
                "junk",
            ]
        }
        json_client, opener = client(json.dumps(body))

        pulled = unwrap(PubSubRest(client=json_client).pull(subscription="s", max_messages=5))

        assert pulled == [
            ReceivedMessage(
                ack_id="a1", data=b"{}", attributes={"ce-type": "t"}, publish_time=EXPIRES_AT
            ),
            ReceivedMessage(ack_id="a2", data=b"", attributes={}, publish_time=None),
        ]
        assert (opener.requests[0].full_url, opener.requests[0].data) == (
            f"{PUBSUB_API}/s:pull",
            b'{"maxMessages": 5}',
        )

    def test_ack_sends_the_ids(self) -> None:
        json_client, opener = client("{}")

        unwrap(PubSubRest(client=json_client).ack(subscription="s", ack_ids=["a1"]))

        assert (opener.requests[0].full_url, opener.requests[0].data) == (
            f"{PUBSUB_API}/s:acknowledge",
            b'{"ackIds": ["a1"]}',
        )

    @pytest.mark.parametrize("call", ["pull", "ack"])
    def test_failures_are_returned(self, call: str) -> None:
        json_client, _ = client(http_error(code=403))
        rest = PubSubRest(client=json_client)
        calls = {
            "pull": lambda: rest.pull(subscription="s", max_messages=1),
            "ack": lambda: rest.ack(subscription="s", ack_ids=["a"]),
        }

        assert expect_error(calls[call]()).details == {"status": 403}


def _done(response: object) -> str:
    return json.dumps({"done": True, "response": response})


EXPECTED = SubscriptionState(name="subscriptions/s1", state="ACTIVE", expire_time=EXPIRES_AT)


class TestWorkspaceEventsRest:
    def test_get_reads_the_subscription(self) -> None:
        json_client, opener = client(json.dumps(SUBSCRIPTION))

        state = unwrap(WorkspaceEventsRest(client=json_client).get(name="subscriptions/s1"))

        assert (state, opener.requests[0].full_url) == (
            EXPECTED,
            f"{WORKSPACE_EVENTS_API}/subscriptions/s1",
        )

    def test_get_of_a_lapsed_subscription_is_none(self) -> None:
        json_client, _ = client(http_error(code=404))

        assert unwrap(WorkspaceEventsRest(client=json_client).get(name="subscriptions/s1")) is None

    def test_get_failure_is_returned(self) -> None:
        json_client, _ = client(http_error(code=403))

        result = WorkspaceEventsRest(client=json_client).get(name="subscriptions/s1")

        assert expect_error(result).details == {"status": 403}

    def test_get_of_a_nameless_subscription_is_an_error(self) -> None:
        json_client, _ = client("{}")

        result = WorkspaceEventsRest(client=json_client).get(name="subscriptions/s1")

        assert "without a name" in expect_error(result).error

    def test_create_subscribes_to_reactions_with_resources(self) -> None:
        json_client, opener = client(_done(SUBSCRIPTION))
        spec = SubscriptionSpec(topic="projects/p/topics/t")

        state = unwrap(WorkspaceEventsRest(client=json_client).create(spec=spec))

        assert state == EXPECTED
        assert json.loads(opener.requests[0].data or b"") == {
            "targetResource": "//chat.googleapis.com/spaces/-",
            "eventTypes": [
                "google.workspace.chat.reaction.v1.created",
                "google.workspace.chat.reaction.v1.deleted",
            ],
            "notificationEndpoint": {"pubsubTopic": "projects/p/topics/t"},
            "payloadOptions": {"includeResource": True},
        }

    def test_renew_asks_for_the_longest_ttl(self) -> None:
        json_client, opener = client(_done(SUBSCRIPTION))

        unwrap(WorkspaceEventsRest(client=json_client).renew(name="subscriptions/s1"))

        assert (opener.requests[0].get_method(), opener.requests[0].full_url) == (
            "PATCH",
            f"{WORKSPACE_EVENTS_API}/subscriptions/s1?updateMask=ttl",
        )

    def test_reactivate_posts_to_the_subscription(self) -> None:
        json_client, opener = client(_done(SUBSCRIPTION))

        unwrap(WorkspaceEventsRest(client=json_client).reactivate(name="subscriptions/s1"))

        assert opener.requests[0].full_url == f"{WORKSPACE_EVENTS_API}/subscriptions/s1:reactivate"

    @pytest.mark.parametrize(
        ("operation", "fragment"),
        [
            (json.dumps({"done": False}), "has not finished"),
            (json.dumps({"done": True, "error": {"message": "denied"}}), "denied"),
            (json.dumps({"done": True}), "without a subscription"),
        ],
    )
    def test_unfinished_or_failed_operations_are_errors(
        self, operation: str, fragment: str
    ) -> None:
        json_client, _ = client(operation)

        result = WorkspaceEventsRest(client=json_client).create(spec=SubscriptionSpec(topic="t"))

        assert fragment in expect_error(result).error

    @pytest.mark.parametrize("call", ["create", "renew", "reactivate"])
    def test_http_failures_are_returned(self, call: str) -> None:
        json_client, _ = client(http_error(code=400))
        rest = WorkspaceEventsRest(client=json_client)
        calls = {
            "create": lambda: rest.create(spec=SubscriptionSpec(topic="t")),
            "renew": lambda: rest.renew(name="subscriptions/s1"),
            "reactivate": lambda: rest.reactivate(name="subscriptions/s1"),
        }

        assert expect_error(calls[call]()).details == {"status": 400}
