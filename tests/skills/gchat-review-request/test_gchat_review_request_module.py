"""Tests for the importable gchat_review_request module."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dev10x.skills.notifications import gchat_review_request as mod


class TestResolveProjectConfig:
    def test_configured_repo_returns_space_and_mentions(self) -> None:
        config = {"projects": {"my-app": {"space": "tt-reviews", "mentions": ["@team"]}}}
        assert mod.resolve_project_config(config=config, repo_name="my-app") == {
            "skip": False,
            "ask": False,
            "space": "tt-reviews",
            "mentions": ["@team"],
        }

    def test_skip_repo(self) -> None:
        config = {"projects": {"my-app": {"skip": True}}}
        result = mod.resolve_project_config(config=config, repo_name="my-app")
        assert result["skip"] is True

    def test_unconfigured_defaults_to_ask(self) -> None:
        result = mod.resolve_project_config(config={"default_action": "ask"}, repo_name="x")
        assert result["ask"] is True

    def test_unconfigured_default_skip(self) -> None:
        result = mod.resolve_project_config(config={"default_action": "skip"}, repo_name="x")
        assert result["skip"] is True


class TestResolveMention:
    def test_group_alias_uses_native_token(self) -> None:
        cfg = {"user_groups": {"@team": "<GROUP_TOKEN>"}}
        assert mod.resolve_mention(mention="@team", gchat_config=cfg) == "<GROUP_TOKEN>"

    def test_user_alias_expands_to_user_id(self) -> None:
        cfg = {"users": {"alice": {"chat_user_id": "123"}}}
        assert mod.resolve_mention(mention="@alice", gchat_config=cfg) == "<users/123>"

    def test_unknown_mention_passthrough(self) -> None:
        assert mod.resolve_mention(mention="@ghost", gchat_config={}) == "@ghost"


class TestFormatReviewMessage:
    def test_includes_link_title_and_jtbd(self) -> None:
        msg = mod.format_review_message(
            pr_number=42,
            repo="org/my-app",
            pr_url="https://github.com/org/my-app/pull/42",
            pr_title="Fix payment routing",
            jtbd="When a customer pays, I want speed, so I can checkout.",
            resolved_mentions=["<GROUP_TOKEN>"],
        )
        assert "<https://github.com/org/my-app/pull/42|my-app#42>" in msg
        assert "*Fix payment routing*" in msg
        assert msg.startswith("<GROUP_TOKEN> Please review")
        assert "> When a customer pays" in msg


class TestCmdPrepare:
    def test_skip_emits_skip_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            mod, "load_yaml", lambda path: {"projects": {"my-app": {"skip": True}}}
        )
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))
        import json

        out = json.loads(capsys.readouterr().out)
        assert out["skip"] is True

    def test_configured_emits_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_load(path):  # noqa: ANN001, ANN202
            if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
                return {"projects": {"my-app": {"space": "tt-reviews", "mentions": ["@team"]}}}
            return {"user_groups": {"@team": "<GROUP>"}}

        monkeypatch.setattr(mod, "load_yaml", fake_load)
        monkeypatch.setattr(
            mod,
            "gh_json",
            lambda args: {
                "number": 42,
                "title": "Fix routing",
                "body": "When x, I want y, so I can z.",
                "url": "https://github.com/org/my-app/pull/42",
            },
        )
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))
        import json

        out = json.loads(capsys.readouterr().out)
        assert out["space"] == "tt-reviews"
        assert "<GROUP> Please review" in out["message"]
        assert out["resolved_mentions"] == ["<GROUP>"]

    def test_unconfigured_emits_ask_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(mod, "load_yaml", lambda path: {"default_action": "ask"})
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))
        import json

        out = json.loads(capsys.readouterr().out)
        assert out["ask"] is True
        assert out["skip"] is False
        assert out["space"] is None
        assert out["message"] is None
