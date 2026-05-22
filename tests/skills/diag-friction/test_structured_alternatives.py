"""Schema tests for the structured-alternatives knowledge base (GH-282)."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml not installed")

KB_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "diag-friction"
    / "references"
    / "structured-alternatives.yaml"
)


@pytest.fixture(scope="module")
def kb_data() -> dict:
    return yaml.safe_load(KB_PATH.read_text())


class TestKnowledgeBaseSchema:
    def test_kb_file_exists(self) -> None:
        assert KB_PATH.is_file(), f"KB missing at {KB_PATH}"

    def test_kb_has_alternatives_and_prefixes(self, kb_data: dict) -> None:
        assert "alternatives" in kb_data
        assert "inline_code_prefixes" in kb_data
        assert isinstance(kb_data["alternatives"], list)
        assert isinstance(kb_data["inline_code_prefixes"], list)

    def test_every_alternative_has_required_fields(self, kb_data: dict) -> None:
        required_fields = {"use_case", "detection_keywords", "tool", "example"}
        for entry in kb_data["alternatives"]:
            missing = required_fields - entry.keys()
            assert not missing, f"Entry {entry.get('use_case')!r} missing fields: {missing}"
            assert isinstance(entry["detection_keywords"], list)
            assert isinstance(entry["tool"], str) and entry["tool"]
            assert isinstance(entry["example"], str) and entry["example"]

    def test_canonical_use_cases_are_present(self, kb_data: dict) -> None:
        tools_by_use_case = {entry["use_case"]: entry["tool"] for entry in kb_data["alternatives"]}
        # The GH-271 evidence #55 motivating cases — these MUST stay
        # in the catalog so /Dev10x:diag-friction can surface them.
        assert any("jq" == tool for tool in tools_by_use_case.values())
        assert any("yq" == tool for tool in tools_by_use_case.values())
        assert any("yamllint" == tool for tool in tools_by_use_case.values())
        assert any("actionlint" == tool for tool in tools_by_use_case.values())
        assert any("curl" == tool for tool in tools_by_use_case.values())

    def test_fallback_entry_has_empty_keywords(self, kb_data: dict) -> None:
        fallback_entries = [
            entry for entry in kb_data["alternatives"] if entry["detection_keywords"] == []
        ]
        assert len(fallback_entries) == 1, "Exactly one fallback entry expected"
        assert "tools" in fallback_entries[0]["tool"].lower() or (
            "~/.claude" in fallback_entries[0]["tool"]
        )

    def test_inline_code_prefixes_cover_common_runtimes(
        self,
        kb_data: dict,
    ) -> None:
        prefixes = set(kb_data["inline_code_prefixes"])
        # Motivating cases from the ticket
        assert "python -c" in prefixes
        assert "python3 -c" in prefixes
        assert "sh -c" in prefixes
        assert "node -e" in prefixes


class TestSimulatedDetection:
    """Smoke-test the documented Step 3c-pre matching algorithm."""

    def _match(self, command_body: str, kb_data: dict) -> str:
        for entry in kb_data["alternatives"]:
            for keyword in entry["detection_keywords"]:
                if keyword in command_body:
                    return entry["tool"]
        # Fallback path
        for entry in kb_data["alternatives"]:
            if entry["detection_keywords"] == []:
                return entry["tool"]
        raise AssertionError("KB missing fallback entry")

    def test_yaml_safe_load_surfaces_yq(self, kb_data: dict) -> None:
        body = "import yaml; yaml.safe_load(open('x.yml'))"
        assert self._match(body, kb_data) == "yq"

    def test_json_loads_surfaces_jq(self, kb_data: dict) -> None:
        body = "import json; json.loads(open('x.json').read())"
        assert self._match(body, kb_data) == "jq"

    def test_unknown_body_falls_back_to_tools_extraction(
        self,
        kb_data: dict,
    ) -> None:
        body = "some bespoke business logic with no matchable keyword"
        result = self._match(body, kb_data)
        assert "tools" in result or "~/.claude" in result
