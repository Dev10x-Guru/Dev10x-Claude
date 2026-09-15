"""GH-1307: an unconfigured repo gets the cardsV2 default too.

``resolve_project_config`` carried ``card`` onto the ask resolution
correctly — GH-1115's default was right at that layer, and its tests
pinned it there. What discarded it was ``cmd_prepare``'s ask branch,
which printed a hand-written six-key dict instead of the envelope
``SKILL.md`` documents. So a repo with no config entry silently posted
plain text, and no test noticed because none of them reached past the
resolver.

These tests exercise the ask path end to end, which is the layer that
was actually broken.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from dev10x.skills.notifications import gchat_review_request as mod

PR_URL = "https://github.com/org/my-app/pull/42"

_PR = {
    "number": 42,
    "title": "Fix routing",
    "body": "**When** a shop reprices, **the owner wants** the total to hold",
    "url": PR_URL,
    "headRefOid": "abc123",
}


@pytest.fixture()
def unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A review config that names some other repo, so ours falls through to ask."""

    def fake_load(path: Any) -> dict:
        if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
            return {"projects": {"some-other-repo": {"space": "s"}}}
        return {}

    monkeypatch.setattr(mod, "load_yaml", fake_load)
    monkeypatch.setattr(mod, "gh_json", lambda args, **kwargs: _PR)


def _prepare(capsys: pytest.CaptureFixture[str]) -> dict:
    mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))
    return json.loads(capsys.readouterr().out)


class TestTheAskPathCarriesTheCardDefault:
    def test_the_card_is_rendered(
        self, unconfigured: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        envelope = _prepare(capsys)

        assert envelope["ask"] is True
        assert envelope["card"] is not None, (
            "an unconfigured repo must still get the GH-1115 cardsV2 default"
        )

    def test_the_documented_keys_are_all_present(
        self, unconfigured: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """SKILL.md Step 1 lists these as prepare's output; the old dict had six."""
        envelope = _prepare(capsys)

        assert set(envelope) >= {
            "skip",
            "ask",
            "space",
            "mentions",
            "resolved_mentions",
            "message",
            "reason",
            "pr_url",
            "pr_title",
            "preview_url",
            "card",
            "fallback_text",
        }

    def test_only_the_space_is_unknown(
        self, unconfigured: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Everything the card needs comes from the PR, not from the config."""
        envelope = _prepare(capsys)

        assert envelope["space"] is None
        assert envelope["pr_url"] == PR_URL
        assert envelope["pr_title"] == "Fix routing"
        assert envelope["fallback_text"]

    def test_the_reason_still_asks_for_a_space(
        self, unconfigured: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        envelope = _prepare(capsys)

        assert "my-app" in envelope["reason"]
        assert "space" in envelope["reason"]


class TestOptingOutStillWins:
    def test_a_global_card_default_of_false_reaches_the_ask_path(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A null card here means "opted out", never "the default was lost"."""

        def fake_load(path: Any) -> dict:
            if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
                return {"default_card": False, "projects": {}}
            return {}

        monkeypatch.setattr(mod, "load_yaml", fake_load)
        monkeypatch.setattr(mod, "gh_json", lambda args, **kwargs: _PR)

        envelope = _prepare(capsys)

        assert envelope["ask"] is True
        assert envelope["card"] is None
        assert PR_URL in envelope["message"]


class TestASkippedRepoIsUntouched:
    def test_skip_short_circuits_before_the_pr_is_fetched(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The ask path now costs a `gh pr view`; the skip path must not."""

        def fake_load(path: Any) -> dict:
            if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
                return {"projects": {"my-app": {"skip": True}}}
            return {}

        def explode(args: list[str], **kwargs: Any) -> Any:
            raise AssertionError("a skipped repo must not call gh")

        monkeypatch.setattr(mod, "load_yaml", fake_load)
        monkeypatch.setattr(mod, "gh_json", explode)

        envelope = _prepare(capsys)

        assert envelope["skip"] is True
