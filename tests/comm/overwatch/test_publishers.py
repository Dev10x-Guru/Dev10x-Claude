"""Tests for the artifact share menu publishers (GH-1938)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.comm.overwatch.publishers import (
    CLAUDE_AI,
    Publisher,
    PublisherConfig,
    builtin_publishers,
    load_publishers,
)

EXAMPLE = Publisher(
    id="example", label="Example docs", kind="mcp", target="mcp__example__publish_page"
)
GOOD = """\
dev:
  checkout: /somewhere
artifact_publishers:
  - id: example
    label: Example docs
    kind: mcp
    target: mcp__example__publish_page
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return tmp_path / "overwatch.yaml"


class TestInstruction:
    @pytest.mark.parametrize(
        ("publisher", "expected"),
        [
            (
                CLAUDE_AI,
                "Use the export path of dev10x:artifact to publish it as a claude.ai Artifact",
            ),
            (
                Publisher(id="docs", label="Docs", kind="skill", target="example:publish"),
                "Run Skill(example:publish) to publish it",
            ),
            (EXAMPLE, "Call mcp__example__publish_page to publish it"),
            (
                Publisher(
                    id="p",
                    label="P",
                    kind="prompt",
                    target="Upload {path} as {id} titled {title} {other}.",
                ),
                "Upload /a/r.json as r titled Review {other}",
            ),
        ],
        ids=["builtin", "skill", "mcp", "prompt"],
    )
    def test_words_the_request(self, publisher: Publisher, expected: str) -> None:
        assert publisher.instruction(path="/a/r.json", artifact_id="r", title="Review") == expected

    def test_prompt_template_gets_a_one_line_title(self) -> None:
        publisher = Publisher(id="p", label="P", kind="prompt", target="Upload as {title}.")

        assert (
            publisher.instruction(path="/a/r.json", artifact_id="r", title="Re\nview  page")
            == "Upload as Re view page"
        )

    def test_menu_entry(self) -> None:
        assert EXAMPLE.to_dict() == {"id": "example", "label": "Example docs"}


class TestLoad:
    def test_missing_file_gives_the_builtin(self, config: Path) -> None:
        assert load_publishers(path=config) == builtin_publishers()

    def test_reads_configured_publishers(self, config: Path) -> None:
        config.write_text(GOOD)

        assert load_publishers(path=config) == PublisherConfig(publishers=[CLAUDE_AI, EXAMPLE])

    def test_empty_file(self, config: Path) -> None:
        config.write_text("")

        assert load_publishers(path=config) == builtin_publishers()

    @pytest.mark.parametrize(
        ("text", "error"),
        [
            ("[1, 2]", "must hold a mapping"),
            ("a: [", "is not valid YAML"),
            ("artifact_publishers: nope", "artifact_publishers: must be a list"),
        ],
    )
    def test_unusable_file(self, config: Path, text: str, error: str) -> None:
        config.write_text(text)

        loaded = load_publishers(path=config)

        assert (loaded.publishers, error in loaded.errors[0]) == ([CLAUDE_AI], True)

    def test_unreadable_file(self, config: Path) -> None:
        config.mkdir()

        assert "is unreadable" in load_publishers(path=config).errors[0]

    @pytest.mark.parametrize(
        ("entry", "error"),
        [
            ("- nope", "artifact_publishers[0]: must be a mapping"),
            (
                "- {id: Bad Id, label: L, kind: mcp, target: t}",
                "artifact_publishers[0].id: must be a slug",
            ),
            (
                "- {id: claude-ai, label: L, kind: mcp, target: t}",
                "artifact_publishers[0].id: duplicate publisher id 'claude-ai'",
            ),
            (
                "- {id: docs, label: '', kind: mcp, target: t}",
                "artifact_publishers[0].label: must be a non-empty string",
            ),
            (
                "- {id: docs, label: L, kind: mcp}",
                "artifact_publishers[0].target: must be a non-empty string",
            ),
            (
                "- {id: docs, label: L, kind: email, target: t}",
                "artifact_publishers[0].kind: must be one of skill, mcp, prompt",
            ),
        ],
    )
    def test_skips_and_reports_bad_entries(self, config: Path, entry: str, error: str) -> None:
        config.write_text(
            "artifact_publishers:\n"
            f"  {entry}\n"
            "  - {id: example, label: Example docs, kind: mcp, "
            "target: mcp__example__publish_page}\n"
        )

        assert load_publishers(path=config) == PublisherConfig(
            publishers=[CLAUDE_AI, EXAMPLE], errors=[error]
        )

    def test_defaults_to_the_user_file(self, config_home: Path) -> None:
        config_home.mkdir(parents=True)
        (config_home / "overwatch.yaml").write_text(GOOD)

        assert load_publishers().publishers == [CLAUDE_AI, EXAMPLE]


class TestFind:
    @pytest.mark.parametrize(("publisher_id", "found"), [("claude-ai", CLAUDE_AI), ("x", None)])
    def test_find(self, publisher_id: str, found: Publisher | None) -> None:
        assert builtin_publishers().find(publisher_id=publisher_id) == found
