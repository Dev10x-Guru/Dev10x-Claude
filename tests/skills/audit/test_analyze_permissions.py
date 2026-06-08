"""Tests for the skills CLI adapter (GH-244, I1 / ADR-0008).

The analysis logic moved to ``dev10x.audit.permissions_model``; this
module is now a thin adapter that re-exports those names and provides
the ``main`` entry point used by the skill-audit Bash pipeline. These
tests cover the adapter: that it re-exports the model symbols and that
``main`` drives the pipeline to a file or to stdout.
"""

import json
import sys
from pathlib import Path

import pytest

from dev10x.skills.audit import analyze_permissions as adapter

TRANSCRIPT = "## Turn 1 [12:00:00] ASSISTANT\n\n**Tool: `Bash`**\n```\ncommand=ls -la\n```\n"


def test_reexports_logic_from_permissions_model() -> None:
    from dev10x.audit import permissions_model

    assert adapter.analyze_permissions is permissions_model.analyze_permissions
    assert adapter.Finding is permissions_model.Finding
    assert adapter.write_output is permissions_model.write_output
    assert "main" in adapter.__all__


def test_main_no_args_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["analyze-permissions.py"])
    with pytest.raises(SystemExit):
        adapter.main()


def test_main_writes_report_to_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    transcript = tmp_path / "transcript.md"
    # `gh pr edit` is flagged as EXIT_CODE_FALSE_POSITIVE by
    # detect_known_friction, so main() exercises the extra-finding
    # renumber loop in addition to the base analysis.
    transcript.write_text(
        TRANSCRIPT
        + "## Turn 2 [12:01:00] ASSISTANT\n\n"
        + "**Tool: `Bash`**\n```\ncommand=gh pr edit 5 --title x\n```\n"
    )
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))
    output = tmp_path / "report.md"

    monkeypatch.setattr(
        sys,
        "argv",
        ["analyze-permissions.py", str(transcript), str(settings), str(output)],
    )
    adapter.main()

    assert output.exists()
    assert "# Phase 4: Permission Friction Analysis" in output.read_text()


def test_main_surfaces_hook_denials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    transcript = tmp_path / "transcript.md"
    # A denied call lives only in a tool-result block, which the input
    # parser drops — main() must still surface it via detect_hook_denials.
    transcript.write_text(
        TRANSCRIPT
        + "## Turn 2 [12:01:00] USER\n\n"
        + "<details><summary>Tool result (toolu_x...)</summary>\n\n"
        + "```\nBLOCKED: Direct psql calls are not allowed.\n```\n</details>\n\n"
    )
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))
    output = tmp_path / "report.md"

    monkeypatch.setattr(
        sys,
        "argv",
        ["analyze-permissions.py", str(transcript), str(settings), str(output)],
    )
    adapter.main()

    assert "HOOK_DENIAL" in output.read_text()


def test_main_writes_to_stdout_with_default_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    transcript = tmp_path / "transcript.md"
    transcript.write_text(TRANSCRIPT)

    # No settings/output args — settings defaults to ~/.claude/settings.local.json
    # (absent under the tmp HOME) and the report goes to stdout.
    monkeypatch.setattr(sys, "argv", ["analyze-permissions.py", str(transcript)])
    adapter.main()

    captured = capsys.readouterr()
    assert "# Phase 4: Permission Friction Analysis" in captured.out
