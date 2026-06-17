"""Tests for `dev10x github review-rules` (GH-352).

Contract class: mock
  The pure digest renderer is tested directly; the command path patches
  the GH-349 author so no ``gh`` subprocess runs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from dev10x.cli import cli
from dev10x.commands.github import _render_digest
from dev10x.domain.common.result import err, ok


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _rule(*, slug: str = "block-chaining", content: str = "# Block chaining\n\nbody") -> dict:
    return {"slug": slug, "title": "Block chaining", "path": f"p/{slug}.md", "content": content}


class TestGithubGroupRegistration:
    def test_group_exposed(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["github", "--help"])

        assert result.exit_code == 0
        assert "review-rules" in result.output

    def test_review_rules_help_lists_options(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["github", "review-rules", "--help"])

        assert result.exit_code == 0
        assert "--repo" in result.output
        assert "--min-frequency" in result.output
        assert "--max-fp-rate" in result.output


class TestRenderDigest:
    def test_includes_rule_bodies_and_routing(self) -> None:
        digest = _render_digest(
            rules=[_rule(content="# A\n\naaa"), _rule(slug="b", content="# B\n\nbbb")],
            routing_fragment="| Generated rule | Reviewer agent |",
        )
        assert digest.startswith("# Learned review rules")
        assert "2 validated pattern(s)" in digest
        assert "# A" in digest and "# B" in digest
        assert "---" in digest  # separator between rule bodies
        assert "## Routing" in digest
        assert "| Generated rule | Reviewer agent |" in digest

    def test_empty_rules_yield_placeholder(self) -> None:
        digest = _render_digest(rules=[], routing_fragment="ignored")
        assert "# Learned review rules" in digest
        assert "No validated review-comment patterns" in digest
        assert "## Routing" not in digest


class TestReviewRulesCommand:
    @patch(
        "dev10x.github.rule_authoring.author_reference_rules",
        new_callable=AsyncMock,
    )
    def test_happy_path_prints_digest(
        self,
        mock_author: AsyncMock,
        runner: CliRunner,
    ) -> None:
        mock_author.return_value = ok(
            {
                "rules": [_rule(content="# Block chaining\n\navoid && chaining")],
                "routing_fragment": "| `p/block-chaining.md` | `reviewer-generic` |",
                "summary": {"rules_authored": 1},
            }
        )

        result = runner.invoke(cli, ["github", "review-rules", "--repo", "o/r"])

        assert result.exit_code == 0, result.output
        assert "Learned review rules" in result.output
        assert "avoid && chaining" in result.output
        assert "reviewer-generic" in result.output
        mock_author.assert_awaited_once()
        assert mock_author.await_args.kwargs["repos"] == ["o/r"]

    @patch(
        "dev10x.github.rule_authoring.author_reference_rules",
        new_callable=AsyncMock,
    )
    def test_no_repo_passes_none(
        self,
        mock_author: AsyncMock,
        runner: CliRunner,
    ) -> None:
        mock_author.return_value = ok({"rules": [], "routing_fragment": "x", "summary": {}})

        result = runner.invoke(cli, ["github", "review-rules"])

        assert result.exit_code == 0, result.output
        assert "No validated review-comment patterns" in result.output
        assert mock_author.await_args.kwargs["repos"] is None

    @patch(
        "dev10x.github.rule_authoring.author_reference_rules",
        new_callable=AsyncMock,
    )
    def test_mining_error_exits_nonzero(
        self,
        mock_author: AsyncMock,
        runner: CliRunner,
    ) -> None:
        mock_author.return_value = err("no repository specified")

        result = runner.invoke(cli, ["github", "review-rules"])

        assert result.exit_code == 1
        assert "no repository specified" in result.output
