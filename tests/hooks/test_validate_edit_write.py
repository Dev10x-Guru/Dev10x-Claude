"""Tests for validate-edit-write.py — unified Edit|Write validator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = _REPO_ROOT / "hooks" / "scripts" / "validate-edit-write.py"


def _run_hook(
    *,
    tool_name: str,
    file_path: str,
    content: str = "",
) -> subprocess.CompletedProcess[str]:
    payload = {
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path, "new_string": content},
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestEvalInSkills:
    @pytest.mark.parametrize(
        "file_path",
        [
            "/home/user/.claude/skills/deploy/SKILL.md",
            "/home/user/.claude/skills/deploy/run.sh",
        ],
    )
    def test_blocks_eval_in_skill_files(self, file_path: str) -> None:
        result = _run_hook(
            tool_name="Edit",
            file_path=file_path,
            content='eval "$GENERATED_COMMAND"',
        )
        assert result.returncode == 2
        stderr = json.loads(result.stderr)
        assert stderr["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "eval" in stderr["systemMessage"].lower()

    def test_blocks_eval_with_dollar_sign(self) -> None:
        result = _run_hook(
            tool_name="Write",
            file_path="/home/user/.claude/skills/test/run.sh",
            content="eval $(generate_command)",
        )
        assert result.returncode == 2

    def test_allows_skill_file_without_eval(self) -> None:
        result = _run_hook(
            tool_name="Write",
            file_path="/home/user/.claude/skills/deploy/run.sh",
            content="echo 'safe content'",
        )
        assert result.returncode == 0

    def test_allows_non_skill_file_with_eval(self) -> None:
        result = _run_hook(
            tool_name="Edit",
            file_path="/work/project/scripts/build.sh",
            content='eval "$COMMAND"',
        )
        assert result.returncode == 0


class TestSensitiveFiles:
    @pytest.mark.parametrize(
        "file_path",
        [
            "/work/project/.env",
            "/work/project/secrets.env",
            "/work/project/credentials.json",
            "/work/project/.secret",
            "/work/project/config/.env.production",
            "/work/project/deploy/secrets.env.local",
            # GH-1287: the credential STORES stay blocked. Narrowing the
            # rule to fix the source-file false positive must not admit
            # any of these — a first attempt matched exact basenames and
            # silently dropped every decorated name below, which is most
            # of the real ones.
            "/home/dev/.aws/credentials",
            "/work/project/credentials",
            "/work/project/credentials.ini",
            "/work/project/credentials.yaml",
            "/home/dev/.git-credentials",
            "/home/dev/.config/gcloud/application_default_credentials.json",
            "/work/project/deploy/service-account-credentials.json",
            "/work/project/prod_credentials.yaml",
            "/home/dev/aws.credentials",
            "/etc/app/credentials.d/token",
            "/home/dev/.config/app/credentials/prod.json",
            "/work/project/CREDENTIALS.JSON",
        ],
    )
    def test_blocks_sensitive_file_paths(self, file_path: str) -> None:
        result = _run_hook(tool_name="Edit", file_path=file_path)
        assert result.returncode == 2
        stderr = json.loads(result.stderr)
        assert stderr["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert (
            "sensitive" in stderr["systemMessage"].lower() or file_path in stderr["systemMessage"]
        )

    @pytest.mark.parametrize(
        "file_path",
        [
            "/work/project/src/main.py",
            "/work/project/README.md",
            "/work/project/config/database.yml",
            "/work/project/environment.py",
            "/work/project/config/settings.py",
            "/tmp/Dev10x/gh-issues/001-setup.json",
            "/tmp/Dev10x/gh-issues/001-setup.env.json",
            # GH-1287: source and docs that merely NAME credentials. The
            # old substring rule matched the whole path, so each of these
            # was hard-blocked with "ask the user to edit it manually" —
            # unanswerable in an unattended run.
            "/work/project/src/pkg/credentials.py",
            "/work/project/tests/test_credentials.py",
            "/work/project/src/pkg/credentials_store.ts",
            "/work/project/docs/credentials-setup.md",
            "/work/project/src/credentials/loader.py",
        ],
    )
    def test_allows_non_sensitive_files(self, file_path: str) -> None:
        result = _run_hook(tool_name="Edit", file_path=file_path)
        assert result.returncode == 0


class TestToolFiltering:
    def test_allows_regular_python_file(self) -> None:
        result = _run_hook(
            tool_name="Edit",
            file_path="/work/project/src/main.py",
            content="print('hello')",
        )
        assert result.returncode == 0

    def test_ignores_non_edit_tools(self) -> None:
        result = _run_hook(
            tool_name="Read",
            file_path="/home/user/.claude/skills/test.sh",
            content='eval "$COMMAND"',
        )
        assert result.returncode == 0


class TestMalformedInput:
    def test_handles_empty_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_handles_invalid_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="{invalid json}",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

    def test_handles_missing_file_path(self) -> None:
        payload = {"tool_name": "Edit", "tool_input": {}}
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
