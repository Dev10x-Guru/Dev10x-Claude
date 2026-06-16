"""Unit tests for dev10x.github.rule_authoring (GH-349).

Contract class: mock
  Doc rendering and routing are pure functions tested without mocks. The
  orchestrator patches the GH-348 validator directly so no ``gh``
  subprocess runs. The write helper uses tmp_path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from dev10x.domain.common.result import ErrorResult, SuccessResult, err, ok

ra = pytest.importorskip("dev10x.github.rule_authoring", reason="dev10x not installed")


def _validated(
    *,
    signature: str = "block chaining",
    frequency: int = 5,
    fp_rate: float = 0.1,
    validated: bool = True,
) -> dict:
    return {
        "signature": signature,
        "frequency": frequency,
        "diff_matches": 1,
        "false_positive_rate": fp_rate,
        "validated": validated,
    }


class TestRuleSlug:
    def test_spaces_and_punctuation_become_hyphens(self) -> None:
        assert ra._rule_slug("block chaining, no &&") == "block-chaining-no"

    def test_empty_signature_falls_back(self) -> None:
        assert ra._rule_slug("   ") == "unnamed-pattern"


class TestRuleTitle:
    def test_capitalizes_first_letter_only(self) -> None:
        assert ra._rule_title("block chaining") == "Block chaining"

    def test_empty_signature_falls_back(self) -> None:
        assert ra._rule_title("") == "Unnamed pattern"


class TestRenderRuleDoc:
    def test_includes_title_tokens_and_confidence(self) -> None:
        doc = ra.render_rule_doc(pattern=_validated(frequency=7, fp_rate=0.2))
        assert doc.startswith("# Block chaining")
        assert "heuristic estimates" in doc
        assert "**Signal tokens:** `block`, `chaining`" in doc
        assert "Reviewer frequency: 7" in doc
        assert "Estimated false-positive rate: 0.2" in doc

    def test_empty_signature_tokens_render_dash(self) -> None:
        doc = ra.render_rule_doc(pattern=_validated(signature=""))
        assert "**Signal tokens:** —" in doc


class TestAuthorRuleDocs:
    def test_only_validated_patterns_produce_docs(self) -> None:
        patterns = [
            _validated(signature="block chaining", validated=True),
            _validated(signature="rejected one", validated=False),
        ]
        docs = ra.author_rule_docs(patterns=patterns)
        assert len(docs) == 1
        assert docs[0].slug == "block-chaining"
        assert docs[0].path == "references/review-checks/generated/block-chaining.md"

    def test_empty_when_none_validated(self) -> None:
        assert ra.author_rule_docs(patterns=[_validated(validated=False)]) == []


class TestRenderRoutingFragment:
    def test_table_rows_for_each_doc(self) -> None:
        docs = ra.author_rule_docs(patterns=[_validated()])
        fragment = ra.render_routing_fragment(docs=docs)
        assert "| Generated rule | Reviewer agent |" in fragment
        assert "`references/review-checks/generated/block-chaining.md`" in fragment
        assert "`reviewer-generic`" in fragment

    def test_no_docs_yields_placeholder(self) -> None:
        assert "No validated patterns" in ra.render_routing_fragment(docs=[])


class TestWriteRuleDocs:
    def test_materializes_files_under_base_dir(self, tmp_path: Path) -> None:
        docs = ra.author_rule_docs(patterns=[_validated()])
        written = ra.write_rule_docs(docs=docs, base_dir=tmp_path)
        target = tmp_path / "references/review-checks/generated/block-chaining.md"
        assert written == [str(target)]
        assert target.read_text(encoding="utf-8").startswith("# Block chaining")


class TestAuthorReferenceRules:
    @pytest.mark.asyncio
    @patch(
        "dev10x.github.pattern_validation.validate_candidate_patterns",
        new_callable=AsyncMock,
    )
    async def test_happy_path_authors_and_summarizes(self, mock_validate: AsyncMock) -> None:
        mock_validate.return_value = ok(
            {
                "validated": [_validated(), _validated(signature="skip me", validated=False)],
                "summary": {"repos_scanned": ["o/r"], "diffs_analyzed": 3},
            }
        )

        result = await ra.author_reference_rules(repos=["o/r"])

        assert isinstance(result, SuccessResult)
        assert len(result.value["rules"]) == 1
        assert result.value["summary"]["rules_authored"] == 1
        assert result.value["summary"]["generated_rules_dir"] == ra.GENERATED_RULES_DIR
        assert "block-chaining" in result.value["routing_fragment"]

    @pytest.mark.asyncio
    @patch(
        "dev10x.github.pattern_validation.validate_candidate_patterns",
        new_callable=AsyncMock,
    )
    async def test_propagates_validation_error(self, mock_validate: AsyncMock) -> None:
        mock_validate.return_value = err("no repository specified")

        result = await ra.author_reference_rules()

        assert isinstance(result, ErrorResult)
        assert result.error == "no repository specified"
