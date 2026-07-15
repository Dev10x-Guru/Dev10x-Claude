"""Tests for the runtime policy-resolution caller (PAP-6, GH-868)."""

from __future__ import annotations

from pathlib import Path

from dev10x.skills.permission.resolve import resolve_report


def _flat_layer(tmp_path: Path, *, allow: list[str]) -> Path:
    path = tmp_path / "projects.yaml"
    body = "base_permissions:\n" + "".join(f"  - {rule}\n" for rule in allow)
    path.write_text(body)
    return path


class TestResolveReport:
    def test_matching_rule_resolves_allow(self, tmp_path: Path) -> None:
        layer = _flat_layer(tmp_path, allow=["Bash(git status:*)"])
        lines = resolve_report(signature="Bash(git status)", user_path=layer)
        assert lines[0] == "Signature: Bash(git status)"
        assert lines[-1] == "Effect:    allow"

    def test_unmatched_signature_reports_none(self, tmp_path: Path) -> None:
        layer = _flat_layer(tmp_path, allow=["Bash(git status:*)"])
        lines = resolve_report(signature="Bash(rm -rf /)", user_path=layer)
        assert lines[-1].startswith("Effect:    none")

    def test_no_layers_loads_zero_policies(self) -> None:
        lines = resolve_report(signature="Bash(git status)")
        assert "Layers:    0 policies loaded" in lines
        assert lines[-1].startswith("Effect:    none")

    def test_context_is_echoed(self, tmp_path: Path) -> None:
        layer = _flat_layer(tmp_path, allow=["Bash(git status:*)"])
        lines = resolve_report(signature="Bash(git status)", context="Dev10x:git", user_path=layer)
        assert "Context:   Dev10x:git" in lines

    def test_unscoped_context_label(self, tmp_path: Path) -> None:
        layer = _flat_layer(tmp_path, allow=["Bash(git status:*)"])
        lines = resolve_report(signature="Bash(git status)", user_path=layer)
        assert "Context:   (unscoped)" in lines
