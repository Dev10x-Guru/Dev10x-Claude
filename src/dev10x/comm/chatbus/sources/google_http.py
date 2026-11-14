"""Google REST transport for the Pub/Sub source (ADR-0035 D1, D8).

One JSON request helper with bounded back-off on 408, 429, the
retryable 5xx and network faults (``dev10x.domain.retry``, per
ADR-0029), plus the two thin REST adapters the Pub/Sub source needs.
The token comes from a caller-supplied provider holding the user's
read grant; this module never loads credentials itself.

[Verify] The request and response shapes follow the published REST
references for Pub/Sub ``projects.subscriptions.pull`` /
``acknowledge`` and Workspace Events ``subscriptions``. They were not
exercised against live Google APIs in the session that wrote this
module.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dev10x.comm.chatbus.sources.pubsub import (
    ReceivedMessage,
    SubscriptionSpec,
    SubscriptionState,
)
from dev10x.comm.skills.notifications.gchat_watch import parse_time
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.retry import RetryPolicy, is_retryable_status

log = logging.getLogger(__name__)

PUBSUB_API = "https://pubsub.googleapis.com/v1"
WORKSPACE_EVENTS_API = "https://workspaceevents.googleapis.com/v1"
REQUEST_TIMEOUT_SECONDS = 30
NOT_FOUND = 404

TokenProvider = Callable[[], Result[str]]
Opener = Callable[..., Any]


@dataclass(frozen=True)
class _Attempt:
    result: Result[dict[str, Any]]
    transient: bool = False
    retry_after: float | None = None


def _retry_after(*, raw: str | None) -> float | None:
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


@dataclass(frozen=True)
class GoogleJsonClient:
    token: TokenProvider
    opener: Opener = urllib.request.urlopen
    sleep: Callable[[float], None] = time.sleep
    policy: RetryPolicy = field(default_factory=RetryPolicy)

    def request(
        self,
        *,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Result[dict[str, Any]]:
        token = self.token()
        if isinstance(token, ErrorResult):
            return token
        outcome = _Attempt(result=err(f"{method} {url} was never attempted"))
        for attempt in range(1, self.policy.attempts + 1):
            outcome = self._once(method=method, url=url, payload=payload, token=token.value)
            if not outcome.transient or attempt == self.policy.attempts:
                break
            delay = self.policy.delay_for(attempt=attempt, retry_after=outcome.retry_after)
            log.warning(
                "Google %s %s failed transiently (attempt %d/%d), retrying in %.2fs",
                method,
                url,
                attempt,
                self.policy.attempts,
                delay,
            )
            self.sleep(delay)
        return outcome.result

    def _once(
        self,
        *,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
        token: str,
    ) -> _Attempt:
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Authorization": f"Bearer {token}"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=UTF-8"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            return _Attempt(
                result=err(
                    f"Google {method} {url} failed (HTTP {exc.code}): {detail}", status=exc.code
                ),
                transient=is_retryable_status(exc.code),
                retry_after=_retry_after(
                    raw=exc.headers.get("Retry-After") if exc.headers else None
                ),
            )
        except urllib.error.URLError as exc:
            host = urllib.parse.urlsplit(url).netloc
            return _Attempt(result=err(f"{host} unreachable: {exc.reason}"), transient=True)
        try:
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError as exc:
            return _Attempt(result=err(f"Google {method} {url} returned invalid JSON: {exc}"))
        return _Attempt(result=ok(parsed if isinstance(parsed, dict) else {}))


def _received(*, raw: Mapping[str, Any]) -> ReceivedMessage | None:
    message = raw.get("message")
    ack_id = raw.get("ackId")
    if not isinstance(message, Mapping) or not isinstance(ack_id, str):
        return None
    attributes = message.get("attributes")
    try:
        data = base64.b64decode(str(message.get("data") or ""), validate=True)
    except (binascii.Error, ValueError):
        data = b""
    return ReceivedMessage(
        ack_id=ack_id,
        data=data,
        attributes={str(k): str(v) for k, v in (attributes or {}).items()}
        if isinstance(attributes, Mapping)
        else {},
        publish_time=parse_time(raw=str(message.get("publishTime") or "")),
    )


@dataclass(frozen=True)
class PubSubRest:
    client: GoogleJsonClient

    def pull(self, *, subscription: str, max_messages: int) -> Result[list[ReceivedMessage]]:
        pulled = self.client.request(
            method="POST",
            url=f"{PUBSUB_API}/{subscription}:pull",
            payload={"maxMessages": max_messages},
        )
        if isinstance(pulled, ErrorResult):
            return pulled
        items = pulled.value.get("receivedMessages") or []
        received = (_received(raw=item) for item in items if isinstance(item, Mapping))
        return ok([message for message in received if message is not None])

    def ack(self, *, subscription: str, ack_ids: Sequence[str]) -> Result[None]:
        acked = self.client.request(
            method="POST",
            url=f"{PUBSUB_API}/{subscription}:acknowledge",
            payload={"ackIds": list(ack_ids)},
        )
        if isinstance(acked, ErrorResult):
            return acked
        return ok(None)


def _subscription(*, raw: Mapping[str, Any]) -> Result[SubscriptionState]:
    name = raw.get("name")
    expire = parse_time(raw=str(raw.get("expireTime") or ""))
    if not isinstance(name, str) or not name or expire is None:
        return err("Workspace Events returned a subscription without a name or expiry")
    return ok(SubscriptionState(name=name, state=str(raw.get("state") or ""), expire_time=expire))


def _operation_result(*, operation: Mapping[str, Any], action: str) -> Result[SubscriptionState]:
    # Create, patch and reactivate answer with a long-running operation.
    if not operation.get("done"):
        return err(f"Workspace Events {action} has not finished; the next tick checks again")
    failure = operation.get("error")
    if isinstance(failure, Mapping):
        return err(f"Workspace Events {action} failed: {failure.get('message', failure)}")
    response = operation.get("response")
    if not isinstance(response, Mapping):
        return err(f"Workspace Events {action} finished without a subscription")
    return _subscription(raw=response)


@dataclass(frozen=True)
class WorkspaceEventsRest:
    client: GoogleJsonClient

    def get(self, *, name: str) -> Result[SubscriptionState | None]:
        fetched = self.client.request(method="GET", url=f"{WORKSPACE_EVENTS_API}/{name}")
        if isinstance(fetched, ErrorResult):
            if fetched.details.get("status") == NOT_FOUND:
                return ok(None)
            return fetched
        return _subscription(raw=fetched.value)

    def create(self, *, spec: SubscriptionSpec) -> Result[SubscriptionState]:
        created = self.client.request(
            method="POST",
            url=f"{WORKSPACE_EVENTS_API}/subscriptions",
            payload={
                "targetResource": spec.target_resource,
                "eventTypes": list(spec.event_types),
                "notificationEndpoint": {"pubsubTopic": spec.topic},
                "payloadOptions": {"includeResource": spec.include_resource},
            },
        )
        if isinstance(created, ErrorResult):
            return created
        return _operation_result(operation=created.value, action="create")

    def renew(self, *, name: str) -> Result[SubscriptionState]:
        # A ttl of 0s asks for the longest lifetime the payload options allow.
        query = urllib.parse.urlencode({"updateMask": "ttl"})
        renewed = self.client.request(
            method="PATCH",
            url=f"{WORKSPACE_EVENTS_API}/{name}?{query}",
            payload={"ttl": "0s"},
        )
        if isinstance(renewed, ErrorResult):
            return renewed
        return _operation_result(operation=renewed.value, action="renew")

    def reactivate(self, *, name: str) -> Result[SubscriptionState]:
        reactivated = self.client.request(
            method="POST", url=f"{WORKSPACE_EVENTS_API}/{name}:reactivate", payload={}
        )
        if isinstance(reactivated, ErrorResult):
            return reactivated
        return _operation_result(operation=reactivated.value, action="reactivate")
