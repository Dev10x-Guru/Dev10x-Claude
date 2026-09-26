"""GH-1262: a Preview App button on review requests for deployed repos.

Reviewing a front-end change means looking at the running app, so the card
should link straight to it. The lookup sits on the notification path, which
must never be delayed or broken by it — most of these tests are about the
unhappy paths staying silent.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from dev10x.skills.notifications import gchat_review_request as mod
from dev10x.skills.notifications._gh import GhCommandError

PR_URL = "https://github.com/org/my-app/pull/42"
PREVIEW_URL = "https://my-app-git-feature.vercel.app"
HEAD_SHA = "abc123"


def wire_gh(monkeypatch: pytest.MonkeyPatch, responses: dict[str, Any]) -> list[str]:
    """Route both `gh_json` (e.g. `pr view`) and `gh_api_json` (`gh api`)
    calls by a substring, normalizing every call to one string in the
    shared log so callers can assert across both (GH-1442: the `gh api`
    endpoints moved onto the Gateway's `gh_api_json`, `pr view` did not).
    """
    calls: list[str] = []

    def _respond(*, key: str, logged: str) -> Any:
        calls.append(logged)
        for marker, response in responses.items():
            if marker in key:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"unexpected gh call: {logged}")

    def fake_gh_json(args: list[str], **kwargs: Any) -> Any:
        joined = " ".join(args)
        return _respond(key=joined, logged=joined)

    def fake_gh_api_json(endpoint: str) -> Any:
        return _respond(key=endpoint, logged=endpoint)

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)
    monkeypatch.setattr(mod, "gh_api_json", fake_gh_api_json)
    return calls


def deployment(*, id_: int = 1, environment: str = "preview") -> dict[str, Any]:
    return {"id": id_, "environment": environment}


def status(*, state: str, url: str | None = PREVIEW_URL) -> dict[str, Any]:
    return {"state": state, "environment_url": url}


class TestResolvePreviewUrl:
    def test_returns_the_url_of_a_successful_deployment(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [status(state="success")],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) == PREVIEW_URL

    def test_the_deployments_query_names_this_head_sha(self, monkeypatch: pytest.MonkeyPatch):
        # The router matches on a substring, so without this the call could
        # query the wrong SHA and every other test here would still pass.
        calls = wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [status(state="success")],
            },
        )

        mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA)

        assert calls[0] == f"repos/org/my-app/deployments?sha={HEAD_SHA}&per_page=10"

    def test_the_status_query_names_the_deployment_it_came_from(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls = wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment(id_=77)],
                "deployments/77/statuses": [status(state="success")],
            },
        )

        mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA)

        assert calls[1] == "repos/org/my-app/deployments/77/statuses"

    def test_a_still_running_deployment_yields_nothing_yet(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [status(state="in_progress", url=None)],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_a_pending_status_above_a_success_still_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # A redeploy in flight must not hide the URL that is live right now.
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [
                    status(state="queued", url=None),
                    status(state="success"),
                ],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) == PREVIEW_URL

    def test_a_newer_failure_supersedes_an_older_success(self, monkeypatch: pytest.MonkeyPatch):
        # Reading past the current verdict would link a torn-down build.
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [
                    status(state="failure", url=None),
                    status(state="success"),
                ],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_no_deployments_is_the_normal_case_not_an_error(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(monkeypatch, {"deployments?sha": []})

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_an_api_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(monkeypatch, {"deployments?sha": GhCommandError("404")})

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_a_status_api_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": GhCommandError("500"),
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    @pytest.mark.parametrize(
        "deployments",
        [
            {"unexpected": "shape"},
            "not a list at all",
            None,
            [None],
            ["not a dict"],
        ],
    )
    def test_a_malformed_deployments_response_resolves_to_nothing(
        self, monkeypatch: pytest.MonkeyPatch, deployments: Any
    ):
        wire_gh(monkeypatch, {"deployments?sha": deployments})

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    @pytest.mark.parametrize(
        "statuses",
        [{"unexpected": "shape"}, "not a list at all", None, [None], ["not a dict"]],
    )
    def test_a_malformed_statuses_response_resolves_to_nothing(
        self, monkeypatch: pytest.MonkeyPatch, statuses: Any
    ):
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": statuses,
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_a_deployment_without_an_id_is_skipped(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(monkeypatch, {"deployments?sha": [{"environment": "preview"}]})

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    @pytest.mark.parametrize("marker", ["deployments?sha", "deployments/1/statuses"])
    def test_unparseable_json_is_swallowed_like_any_other_failure(
        self, monkeypatch: pytest.MonkeyPatch, marker: str
    ):
        # gh_json raises JSONDecodeError, not GhCommandError, when the CLI
        # succeeds but prints something that is not JSON.
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [status(state="success")],
                marker: json.JSONDecodeError("bad", "", 0),
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_a_named_environment_skips_the_others(self, monkeypatch: pytest.MonkeyPatch):
        calls = wire_gh(
            monkeypatch,
            {
                "deployments?sha": [
                    deployment(id_=1, environment="staging"),
                    deployment(id_=2, environment="preview"),
                ],
                "deployments/2/statuses": [status(state="success")],
            },
        )

        result = mod.resolve_preview_url(
            repo="org/my-app", head_sha=HEAD_SHA, environment="preview"
        )

        assert result == PREVIEW_URL
        assert not any("deployments/1/statuses" in c for c in calls)

    def test_without_an_environment_the_first_deployment_that_answers_wins(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment(id_=1), deployment(id_=2)],
                "deployments/1/statuses": [status(state="in_progress", url=None)],
                "deployments/2/statuses": [status(state="success")],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) == PREVIEW_URL

    @pytest.mark.parametrize(
        "hostile",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "//evil.example.com",
            "https://real.example.app|Click here",
            "https://real.example.app>",
            42,
        ],
    )
    def test_a_url_that_is_not_a_plain_web_link_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, hostile: Any
    ):
        # environment_url is written by whoever created the deployment
        # status, so it is third-party input arriving at a click target.
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [status(state="success", url=hostile)],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None

    def test_a_success_with_no_url_resolves_to_nothing(self, monkeypatch: pytest.MonkeyPatch):
        wire_gh(
            monkeypatch,
            {
                "deployments?sha": [deployment()],
                "deployments/1/statuses": [status(state="success", url=None)],
            },
        )

        assert mod.resolve_preview_url(repo="org/my-app", head_sha=HEAD_SHA) is None


class TestResolveProjectConfig:
    def test_preview_is_off_when_the_config_is_silent(self):
        config = {"projects": {"my-app": {"space": "s"}}}

        assert mod.resolve_project_config(config=config, repo_name="my-app")["preview"] is False

    def test_a_repo_opts_in(self):
        config = {"projects": {"my-app": {"space": "s", "preview": True}}}

        assert mod.resolve_project_config(config=config, repo_name="my-app")["preview"] is True

    def test_a_global_default_can_turn_it_on(self):
        config = {"default_preview": True, "projects": {"my-app": {"space": "s"}}}

        assert mod.resolve_project_config(config=config, repo_name="my-app")["preview"] is True

    def test_a_repo_opt_out_beats_the_global_default(self):
        config = {
            "default_preview": True,
            "projects": {"my-app": {"space": "s", "preview": False}},
        }

        assert mod.resolve_project_config(config=config, repo_name="my-app")["preview"] is False

    def test_the_environment_name_is_carried(self):
        config = {"projects": {"my-app": {"space": "s", "preview_environment": "preview"}}}
        resolved = mod.resolve_project_config(config=config, repo_name="my-app")

        assert resolved["preview_environment"] == "preview"


class TestFormatReviewCard:
    def _buttons(self, *, preview_url: str | None) -> list[dict[str, Any]]:
        card = mod.format_review_card(
            pr_number=42,
            repo="org/my-app",
            pr_url=PR_URL,
            pr_title="Fix routing",
            jtbd=None,
            preview_url=preview_url,
        )
        return card["card"]["sections"][0]["widgets"][-1]["buttonList"]["buttons"]

    def test_a_resolved_url_adds_a_second_button(self):
        buttons = self._buttons(preview_url=PREVIEW_URL)

        assert buttons[1] == {
            "text": "Preview App",
            "onClick": {"openLink": {"url": PREVIEW_URL}},
        }

    def test_open_pr_still_comes_first(self):
        assert self._buttons(preview_url=PREVIEW_URL)[0]["text"] == "Open PR"

    def test_no_url_renders_the_card_exactly_as_before(self):
        assert self._buttons(preview_url=None) == [
            {"text": "Open PR", "onClick": {"openLink": {"url": PR_URL}}}
        ]


class TestFormatReviewMessage:
    def test_the_card_less_path_carries_the_url_as_a_line(self):
        message = mod.format_review_message(
            pr_number=42,
            repo="org/my-app",
            pr_url=PR_URL,
            pr_title="Fix routing",
            jtbd=None,
            resolved_mentions=[],
            preview_url=PREVIEW_URL,
        )

        assert f"Preview app: <{PREVIEW_URL}|{PREVIEW_URL}>" in message

    def test_no_url_leaves_the_message_unchanged(self):
        message = mod.format_review_message(
            pr_number=42,
            repo="org/my-app",
            pr_url=PR_URL,
            pr_title="Fix routing",
            jtbd=None,
            resolved_mentions=[],
        )

        assert "Preview app" not in message


class TestCmdPrepare:
    def _wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        card: bool = True,
        preview: bool = True,
        statuses: Any = None,
    ) -> None:
        def fake_load(path):  # noqa: ANN001, ANN202
            if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
                return {
                    "projects": {
                        "my-app": {
                            "space": "tt-reviews",
                            "mentions": [],
                            "card": card,
                            "preview": preview,
                        }
                    }
                }
            return {}

        monkeypatch.setattr(mod, "load_yaml", fake_load)
        wire_gh(
            monkeypatch,
            {
                "pr view": {
                    "number": 42,
                    "title": "Fix routing",
                    "body": "",
                    "url": PR_URL,
                    "headRefOid": HEAD_SHA,
                },
                "deployments?sha": [deployment()],
                "deployments/1/statuses": (
                    statuses if statuses is not None else [status(state="success")]
                ),
            },
        )

    def _output(self, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
        return json.loads(capsys.readouterr().out)

    def test_the_envelope_carries_the_resolved_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        self._wire(monkeypatch)
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))

        assert self._output(capsys)["preview_url"] == PREVIEW_URL

    def test_the_card_gets_both_buttons(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        self._wire(monkeypatch)
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))

        widgets = self._output(capsys)["card"]["card"]["sections"][0]["widgets"]
        assert len(widgets[-1]["buttonList"]["buttons"]) == 2

    def test_a_card_less_repo_gets_the_url_in_the_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        self._wire(monkeypatch, card=False)
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))

        out = self._output(capsys)
        assert out["card"] is None
        assert PREVIEW_URL in out["message"]

    def test_an_opted_out_repo_never_calls_the_deployments_api(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def fake_load(path):  # noqa: ANN001, ANN202
            if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
                return {"projects": {"my-app": {"space": "s", "mentions": []}}}
            return {}

        monkeypatch.setattr(mod, "load_yaml", fake_load)
        calls = wire_gh(
            monkeypatch,
            {
                "pr view": {
                    "number": 42,
                    "title": "Fix routing",
                    "body": "",
                    "url": PR_URL,
                    "headRefOid": HEAD_SHA,
                }
            },
        )
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))

        assert self._output(capsys)["preview_url"] is None
        assert not any("deployments" in c for c in calls)

    def test_a_pr_without_a_head_sha_skips_the_lookup(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def fake_load(path):  # noqa: ANN001, ANN202
            if path == mod.Dev10xConfigDir.gchat_review_config_yaml():
                return {"projects": {"my-app": {"space": "s", "mentions": [], "preview": True}}}
            return {}

        monkeypatch.setattr(mod, "load_yaml", fake_load)
        calls = wire_gh(
            monkeypatch,
            {
                "pr view": {
                    "number": 42,
                    "title": "Fix routing",
                    "body": "",
                    "url": PR_URL,
                    "headRefOid": None,
                }
            },
        )
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))

        assert self._output(capsys)["preview_url"] is None
        assert not any("deployments" in c for c in calls)

    def test_a_deployment_that_has_not_landed_yet_does_not_block_the_ping(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        self._wire(monkeypatch, statuses=[status(state="in_progress", url=None)])
        mod.cmd_prepare(SimpleNamespace(pr=42, repo="org/my-app"))

        out = self._output(capsys)
        assert out["preview_url"] is None
        assert out["card"]["card"]["sections"][0]["widgets"][-1]["buttonList"]["buttons"] == [
            {"text": "Open PR", "onClick": {"openLink": {"url": PR_URL}}}
        ]
