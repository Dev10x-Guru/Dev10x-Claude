"""Tests for the extended detect_known_friction (GH-46)."""

import json
from pathlib import Path

from dev10x.skills.audit.analyze_permissions import (
    ToolCall,
    detect_known_friction,
    parse_additional_directories,
)


class TestParseAdditionalDirectories:
    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        result = parse_additional_directories(str(tmp_path / "missing.json"))
        assert result == []

    def test_returns_empty_when_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not valid")
        assert parse_additional_directories(str(path)) == []

    def test_returns_empty_when_section_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"permissions": {"allow": []}}))
        assert parse_additional_directories(str(path)) == []

    def test_returns_configured_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps({"permissions": {"additionalDirectories": ["/tmp/Dev10x", "/tmp/other"]}})
        )
        assert parse_additional_directories(str(path)) == ["/tmp/Dev10x", "/tmp/other"]


class TestDetectKnownFriction:
    def _call(
        self,
        *,
        tool: str,
        command: str = "",
        file_path: str = "",
        turn: int = 1,
    ) -> ToolCall:
        return ToolCall(
            turn=turn,
            time="00:00:00",
            tool=tool,
            command=command or file_path,
            file_path=file_path,
        )

    def test_flags_write_overwrite_on_mktmp_path(self) -> None:
        calls = [
            self._call(
                tool="Write",
                file_path="/tmp/Dev10x/git/commit-msg.AbCdEf123456.txt",
            )
        ]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=["/tmp/Dev10x"],
        )
        kinds = [f.classification for f in findings]
        assert "WRITE_OVERWRITE_GATE" in kinds

    def test_does_not_flag_write_to_normal_path(self, tmp_path: Path) -> None:
        calls = [self._call(tool="Write", file_path=str(tmp_path / "regular.txt"))]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=[],
            project_root=str(tmp_path),
        )
        kinds = [f.classification for f in findings]
        assert "WRITE_OVERWRITE_GATE" not in kinds

    def test_flags_workspace_gate_for_unregistered_path(self) -> None:
        calls = [self._call(tool="Edit", file_path="/var/foreign/path.txt")]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=["/tmp/Dev10x"],
            project_root="/work/example",
        )
        kinds = [f.classification for f in findings]
        assert "WORKSPACE_GATE" in kinds

    def test_skips_workspace_gate_when_dir_registered(self) -> None:
        calls = [self._call(tool="Read", file_path="/tmp/Dev10x/git/foo.txt")]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=["/tmp/Dev10x"],
            project_root="/work/example",
        )
        # The mktmp pattern doesn't match a plain non-suffixed path,
        # and /tmp/Dev10x is registered so workspace gate also skipped.
        assert findings == []

    def test_skips_workspace_gate_for_project_paths(self, tmp_path: Path) -> None:
        path = tmp_path / "subdir" / "file.py"
        calls = [self._call(tool="Read", file_path=str(path))]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=[],
            project_root=str(tmp_path),
        )
        assert findings == []

    def test_flags_gh_pr_edit_as_exit_code_false_positive(self) -> None:
        calls = [
            self._call(
                tool="Bash",
                command="gh pr edit 37 --body-file /tmp/body.txt",
            )
        ]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=[],
        )
        kinds = [f.classification for f in findings]
        assert "EXIT_CODE_FALSE_POSITIVE" in kinds

    def test_does_not_flag_other_gh_pr_subcommands(self) -> None:
        calls = [
            self._call(tool="Bash", command="gh pr view 37"),
            self._call(tool="Bash", command="gh pr list"),
        ]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=[],
        )
        assert [f.classification for f in findings] == []

    def test_combines_multiple_signals_in_one_run(self) -> None:
        calls = [
            self._call(
                tool="Write",
                file_path="/tmp/Dev10x/git/msg.AbCdEf123456.txt",
            ),
            self._call(
                tool="Bash",
                command="gh pr edit 37 --body-file /tmp/body.txt",
            ),
            self._call(tool="Edit", file_path="/etc/strange.conf"),
        ]
        findings = detect_known_friction(
            calls=calls,
            additional_dirs=[],
            project_root="/work/example",
        )
        kinds = sorted({f.classification for f in findings})
        assert kinds == [
            "EXIT_CODE_FALSE_POSITIVE",
            "WORKSPACE_GATE",
            "WRITE_OVERWRITE_GATE",
        ]
