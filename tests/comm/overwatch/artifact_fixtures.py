"""Shared artifact documents for the GH-1938 tests."""

from __future__ import annotations

import copy
from typing import Any

OWNER = {"session_id": "sid-idle", "name": "mc-updates", "cwd": "/w"}

DOCUMENT: dict[str, Any] = {
    "schema": "dev10x.artifact/v1",
    "id": "rollout-review",
    "title": "Rollout review",
    "description": "Pick a rollout window",
    "meta": {"as_of": "2026-11-14", "sources": "CI", "asked_by": "Janusz"},
    "views": [
        {
            "id": "summary",
            "label": "Summary",
            "group": "Overview",
            "badge": "2",
            "blocks": [
                {"type": "claim", "text": "Ship on Friday"},
                {"type": "prose", "paragraphs": ["One", "Two"]},
                {"type": "callout", "tone": "warn", "text": "Freeze starts Monday"},
                {"type": "kv", "items": [{"key": "Owner", "value": "Janusz"}]},
                {
                    "type": "table",
                    "columns": ["Check", "State"],
                    "rows": [["lint", {"text": "green", "tone": "ok"}], ["docs", {"text": "-"}]],
                },
                {"type": "pills", "items": [{"text": "ready", "tone": "ok"}]},
                {"type": "stats", "items": [{"label": "PRs", "value": "4", "note": "open"}]},
                {"type": "mermaid", "source": "graph TD; A-->B"},
                {"type": "draft", "label": "Reply", "text": "Thanks"},
                {"type": "evidence", "items": [{"claim": "Green", "ref": "CI#1", "check": "ok"}]},
                {
                    "type": "decisions",
                    "items": [{"question": "Ship?", "owner": "Janusz", "control": "ship"}],
                },
            ],
        },
        {
            "id": "decide",
            "label": "Decide",
            "blocks": [
                {"type": "button", "id": "ship", "label": "Ship it", "tone": "primary"},
                {"type": "choice", "id": "window", "label": "Window", "options": ["Fri", "Mon"]},
                {
                    "type": "choice",
                    "id": "regions",
                    "label": "Regions",
                    "options": ["eu", "us"],
                    "multi": True,
                },
                {
                    "type": "form",
                    "id": "notes",
                    "label": "Notes",
                    "submit": "Send",
                    "fields": [
                        {"name": "why", "label": "Why", "kind": "textarea"},
                        {"name": "risk", "label": "Risk", "kind": "select", "options": ["low"]},
                    ],
                },
            ],
        },
    ],
}


def document(**changes: Any) -> dict[str, Any]:
    return {**copy.deepcopy(DOCUMENT), **changes}
