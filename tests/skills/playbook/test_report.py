"""Tests for ``dev10x.skills.playbook.report`` (GH-192)."""

from __future__ import annotations

from dev10x.skills.playbook.compare import compare_playbooks
from dev10x.skills.playbook.report import render_markdown_report


def _diff(default_doc: dict, user_doc: dict):
    return compare_playbooks(
        default_doc=default_doc,
        user_doc=user_doc,
        skill_key="work-on",
        user_path="/u/playbook.yaml",
        default_path="/p/playbook.yaml",
    )


def test_no_findings_emits_up_to_date_message() -> None:
    default = {"defaults": {"feature": {"steps": [{"subject": "A", "type": "detailed"}]}}}
    rendered = render_markdown_report(_diff(default, {}))
    assert "No upstream changes detected" in rendered
    assert "work-on" in rendered


def test_new_step_appears_in_report() -> None:
    default = {
        "defaults": {
            "feature": {
                "steps": [
                    {"subject": "Existing", "type": "detailed"},
                    {"subject": "Brand new step", "type": "detailed"},
                ]
            }
        }
    }
    user = {
        "overrides": [
            {
                "play": "feature",
                "steps": [{"subject": "Existing", "type": "detailed"}],
            }
        ]
    }
    rendered = render_markdown_report(_diff(default, user))
    assert "Brand new step" in rendered
    assert "(new)" in rendered


def test_customized_field_is_marked_preserved() -> None:
    default = {
        "defaults": {
            "feature": {
                "steps": [
                    {"subject": "A", "type": "detailed", "prompt": "default prompt"},
                ]
            }
        }
    }
    user = {
        "overrides": [
            {
                "play": "feature",
                "steps": [
                    {"subject": "A", "type": "detailed", "prompt": "user prompt"},
                ],
            }
        ]
    }
    rendered = render_markdown_report(_diff(default, user))
    assert "customized" in rendered
    assert "prompt" in rendered


def test_upstream_changed_field_shows_default_and_missing_user() -> None:
    default = {
        "defaults": {
            "feature": {
                "steps": [
                    {"subject": "A", "type": "detailed", "prompt": "new default prompt"},
                ]
            }
        }
    }
    user = {
        "overrides": [
            {
                "play": "feature",
                "steps": [{"subject": "A", "type": "detailed"}],
            }
        ]
    }
    rendered = render_markdown_report(_diff(default, user))
    assert "new default prompt" in rendered
    assert "<not set>" in rendered


def test_long_prompts_are_elided() -> None:
    long_prompt = "x " * 200
    default = {
        "defaults": {
            "feature": {"steps": [{"subject": "A", "type": "detailed", "prompt": long_prompt}]}
        }
    }
    user = {
        "overrides": [
            {
                "play": "feature",
                "steps": [{"subject": "A", "type": "detailed"}],
            }
        ]
    }
    rendered = render_markdown_report(_diff(default, user))
    assert "..." in rendered


def test_orphan_play_message_present() -> None:
    default = {"defaults": {"feature": {"steps": []}}}
    user = {"overrides": [{"play": "ghost-play", "steps": [{"subject": "X", "type": "detailed"}]}]}
    rendered = render_markdown_report(_diff(default, user))
    assert "ghost-play" in rendered
    assert "orphan" in rendered


def test_fragment_changes_section_appears() -> None:
    default = {
        "fragments": {
            "shipping": [
                {"subject": "Step1", "type": "detailed"},
                {"subject": "Step2", "type": "detailed"},
            ]
        },
        "defaults": {"feature": {"steps": []}},
    }
    user = {"fragments": {"shipping": [{"subject": "Step1", "type": "detailed"}]}}
    rendered = render_markdown_report(_diff(default, user))
    assert "Fragments with upstream changes" in rendered
    assert "Step2" in rendered
