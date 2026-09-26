"""Parity guard between the Slack and Google Chat notification transports.

GH-1479: the two chat providers share ``domain/retry.py`` and
``domain/dead_letter.py`` (ADR-0029 — shared policy modules, no base
class), but nothing previously asserted the two transport modules
actually *wire in* those shared modules. GH-1423/GH-1421 landed the
retry loop and dead-letter sink on ``slack_notify`` alone; this guard
exists so the next protocol-level fix cannot land on one provider
transport without the other noticing.
"""

from __future__ import annotations

import inspect

from dev10x.domain.dead_letter import record_undelivered
from dev10x.domain.retry import RetryPolicy
from dev10x.skills.notifications import gchat_notify, slack_notify


class TestRetryPolicyParity:
    def test_both_transports_import_retry_policy(self) -> None:
        assert slack_notify.RetryPolicy is RetryPolicy
        assert gchat_notify.RetryPolicy is RetryPolicy

    def test_both_transports_declare_a_module_level_retry_policy(self) -> None:
        assert isinstance(slack_notify._SLACK_RETRY_POLICY, RetryPolicy)
        assert isinstance(gchat_notify._GCHAT_RETRY_POLICY, RetryPolicy)

    def test_both_transports_use_the_same_default_bounds(self) -> None:
        """Neither provider should quietly drift from the shared default."""
        assert (
            slack_notify._SLACK_RETRY_POLICY == gchat_notify._GCHAT_RETRY_POLICY == RetryPolicy()
        )

    def test_both_transports_wrap_the_single_call_in_a_retry_loop(self) -> None:
        """The outer transport function must reference a retry policy."""
        slack_source = inspect.getsource(slack_notify.call_slack_api)
        gchat_source = inspect.getsource(gchat_notify._request_json)
        assert "policy" in slack_source
        assert "policy" in gchat_source


class TestDeadLetterParity:
    def test_both_transports_import_record_undelivered(self) -> None:
        assert slack_notify.record_undelivered is record_undelivered
        assert gchat_notify.record_undelivered is record_undelivered

    def test_both_service_entries_call_record_undelivered_on_failure(self) -> None:
        """``notify_slack`` and ``notify_gchat`` must reference the sink."""
        slack_source = inspect.getsource(slack_notify.notify_slack)
        gchat_source = inspect.getsource(gchat_notify.notify_gchat)
        assert "record_undelivered" in slack_source
        assert "record_undelivered" in gchat_source

    def test_both_service_entries_pass_a_transport_name(self) -> None:
        slack_source = inspect.getsource(slack_notify.notify_slack)
        gchat_source = inspect.getsource(gchat_notify.notify_gchat)
        assert 'transport="slack"' in slack_source
        assert 'transport="gchat"' in gchat_source
