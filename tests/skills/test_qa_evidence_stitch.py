"""QA evidence sheet assembly and its permission surface (GH-1141)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "skills" / "qa-self" / "scripts" / "convert-evidence.sh"
_CATALOG = _REPO_ROOT / "skills" / "upgrade-cleanup" / "projects.yaml"
_BASELINE = _REPO_ROOT / "src" / "dev10x" / "skills" / "permission" / "baseline-permissions.yaml"
_MAP = _REPO_ROOT / "src" / "dev10x" / "validators" / "command-skill-map.yaml"
_QA_SKILL = _REPO_ROOT / "skills" / "qa-self" / "SKILL.md"

_IMAGEMAGICK = shutil.which("magick") or shutil.which("convert")
_SUBPROCESS_TIMEOUT_SECONDS = 60


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
    )


def test_identify_is_a_default_catalog_rule():
    """verify-evidence.py already shells out to it — read-only."""
    data = yaml.safe_load(_CATALOG.read_text()) or {}
    assert "Bash(identify:*)" in data.get("base_permissions", [])


def test_both_imagemagick_spellings_are_grouped():
    """IM7 renamed convert to magick; a rule for one does not cover the other."""
    data = yaml.safe_load(_BASELINE.read_text()) or {}
    group = data["groups"]["imagemagick-evidence"]
    assert group["tier"] == 2
    assert "Bash(magick:*)" in group["rules"]
    assert "Bash(convert:*)" in group["rules"]


def test_qa_self_declares_the_verbs_its_scripts_call():
    frontmatter = _QA_SKILL.read_text().split("---", 2)[1]
    for verb in ("identify", "magick", "convert"):
        assert f"Bash({verb}:*)" in frontmatter


def test_map_steers_raw_composition_to_the_script():
    data = yaml.safe_load(_MAP.read_text()) or {}
    rule = next(r for r in data["rules"] if r["name"] == "qa-evidence-stitch")
    assert rule["hook_block"] is False  # advisory — the script is the fix
    assert "convert-evidence.sh" in rule["except"]
    pattern = re.compile(rule["patterns"][0])
    assert pattern.search("magick /tmp/Dev10x/playwright/run1/1.png -append out.png")
    assert not pattern.search("magick /home/user/photos/1.png -append out.png")


def test_stitch_rejects_a_run_dir_outside_the_sandbox(tmp_path: Path):
    """The bounded output path is what makes the narrow script rule enough."""
    result = _run("stitch", str(tmp_path))
    assert result.returncode == 1
    assert "must live under /tmp/Dev10x/" in result.stderr


def test_stitch_rejects_a_missing_directory():
    result = _run("stitch", "/tmp/Dev10x/playwright/does-not-exist-here")
    assert result.returncode == 1
    assert "not a directory" in result.stderr


def test_usage_lists_stitch():
    result = _run("nonsense")
    assert "stitch" in result.stderr


@pytest.mark.skipif(_IMAGEMAGICK is None, reason="ImageMagick not installed")
def test_stitch_produces_a_sheet_from_multiple_frames():
    run_dir = Path("/tmp/Dev10x/playwright/pytest-stitch-run")
    run_dir.mkdir(parents=True, exist_ok=True)
    frames = [run_dir / f"{n}.png" for n in (1, 2, 3)]
    try:
        for frame in frames:
            subprocess.run(
                [_IMAGEMAGICK, "-size", "40x20", "xc:white", str(frame)],
                check=True,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        result = _run("stitch", str(run_dir))
        assert result.returncode == 0, result.stderr
        sheet = run_dir / "evidence-sheet.png"
        assert sheet.is_file()
        assert result.stdout.strip() == str(sheet)
        assert "3 frames" in result.stderr
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.skipif(_IMAGEMAGICK is None, reason="ImageMagick not installed")
def test_stitch_errors_when_the_run_has_no_frames():
    run_dir = Path("/tmp/Dev10x/playwright/pytest-stitch-empty")
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = _run("stitch", str(run_dir))
        assert result.returncode == 1
        assert "no PNGs found" in result.stderr
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
