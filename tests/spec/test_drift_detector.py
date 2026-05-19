"""Unit tests for dev10x.spec.drift_detector (GH-172)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.spec.drift_detector import DriftKind, detect_drift


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("def known_function():\n    pass\n")
    (src / "models.py").write_text("class KnownModel:\n    pass\n")
    return tmp_path


def _write_spec(tmp_path: Path, body: str) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text(body)
    return spec


class TestDetectDrift:
    def test_missing_spec_is_behavioural(self, tmp_path: Path, project_root: Path) -> None:
        report = detect_drift(spec_path=tmp_path / "missing.md", project_root=project_root)
        assert report.has_behavioural
        assert report.signals[0].kind is DriftKind.BEHAVIOURAL

    def test_no_drift_when_refs_resolve(self, tmp_path: Path, project_root: Path) -> None:
        spec = _write_spec(
            tmp_path,
            "## Architecture\n\nUses `src/foo.py`.\n\n"
            "## Acceptance Criteria\n\nCalls `known_function(`.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert not report.has_drift

    def test_structural_drift_on_missing_file(self, tmp_path: Path, project_root: Path) -> None:
        spec = _write_spec(
            tmp_path,
            "## Architecture\n\nUses `src/gone.py`.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert report.has_structural
        assert not report.has_behavioural

    def test_behavioural_drift_on_missing_callable(
        self, tmp_path: Path, project_root: Path
    ) -> None:
        spec = _write_spec(
            tmp_path,
            "## Acceptance Criteria\n\nMust call `missing_callable(`.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert report.has_behavioural

    def test_both_drift_kinds_reported(self, tmp_path: Path, project_root: Path) -> None:
        spec = _write_spec(
            tmp_path,
            "## Architecture\n\nUses `src/missing.py`.\n\n"
            "## Safeguards\n\n`gone_method(` must be called.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert report.has_structural
        assert report.has_behavioural

    def test_only_known_sections_scanned_for_files(
        self, tmp_path: Path, project_root: Path
    ) -> None:
        spec = _write_spec(
            tmp_path,
            "## Random Notes\n\nWe used to have `src/legacy.py`.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert not report.has_drift

    def test_known_class_resolves(self, tmp_path: Path, project_root: Path) -> None:
        spec = _write_spec(
            tmp_path,
            "## Safeguards\n\nRespect `KnownModel(`.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert not report.has_behavioural

    def test_signals_carry_section_and_detail(self, tmp_path: Path, project_root: Path) -> None:
        spec = _write_spec(
            tmp_path,
            "## Architecture\n\nUses `src/missing.py`.\n",
        )
        report = detect_drift(spec_path=spec, project_root=project_root)
        assert report.signals[0].section == "Architecture"
        assert "missing.py" in report.signals[0].detail
