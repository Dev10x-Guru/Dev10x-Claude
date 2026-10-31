"""GH-1556: hook entries split per plugin without losing or changing one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.core.config.fragments import plugin_order
from dev10x.core.config.hook_fragments import (
    HOOK_FRAGMENTS_DIR,
    HookEntry,
    hook_files,
    merged_hook_entries,
)

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
AUDIT_WRAP_PREFIX = "$CLAUDE_PLUGIN_ROOT/hooks/scripts/audit-wrap "


def _wrapped(*, name: str, script: str) -> str:
    return f"{AUDIT_WRAP_PREFIX}{name} $CLAUDE_PLUGIN_ROOT/hooks/scripts/{script}"


@pytest.fixture(scope="module")
def pre_split_entries() -> set[HookEntry]:
    validate_bash = _wrapped(name="validate-bash", script="validate-bash-command.py")
    return {
        ("SessionStart", "*", _wrapped(name="session-start", script="session-start.py"), 15),
        ("PreToolUse", "Skill", _wrapped(name="skill-pre", script="skill-pre.py"), 5),
        ("PreToolUse", "Bash", validate_bash, 10),
        ("PreToolUse", "Monitor", validate_bash, 10),
        (
            "PreToolUse",
            "Edit|Write",
            _wrapped(name="validate-edit-write", script="validate-edit-write.py"),
            5,
        ),
        ("PreToolUse", "TaskUpdate", _wrapped(name="task-guard", script="task-guard.py"), 5),
        (
            "PreToolUse",
            "AskUserQuestion",
            _wrapped(name="supervisor-decision", script="supervisor-decision.py"),
            3,
        ),
        ("Stop", "*", _wrapped(name="session-stop", script="session-stop.py"), 10),
        (
            "PreCompact",
            "manual|auto",
            _wrapped(name="precompact-context", script="precompact-context.py"),
            5,
        ),
        (
            "PermissionDenied",
            "*",
            _wrapped(name="permission-denied", script="permission-denied.py"),
            10,
        ),
        ("PostToolUse", "Skill", _wrapped(name="skill-post", script="skill-post.py"), 3),
        ("PostToolUse", "Edit|Write", _wrapped(name="ruff-format", script="ruff-format.py"), 15),
        (
            "PostToolUse",
            "TaskCreate|TaskUpdate",
            _wrapped(name="task-plan-sync", script="task-plan-sync.py"),
            5,
        ),
    }


@pytest.fixture(scope="module")
def entries() -> set[HookEntry]:
    return merged_hook_entries(plugin_root=PLUGIN_ROOT)


@pytest.fixture(scope="module")
def fragment_paths() -> list[Path]:
    return sorted((PLUGIN_ROOT / HOOK_FRAGMENTS_DIR).glob("*.json"))


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())


class TestSplitIsLossless:
    def test_merged_entries_equal_the_pre_split_file(
        self,
        entries: set[HookEntry],
        pre_split_entries: set[HookEntry],
    ) -> None:
        assert entries == pre_split_entries

    def test_every_command_is_audit_wrapped(self, entries: set[HookEntry]) -> None:
        assert [
            command for _, _, command, _ in entries if not command.startswith(AUDIT_WRAP_PREFIX)
        ] == []


class TestFragmentFiles:
    def test_every_fragment_is_named_after_a_plugin(self, fragment_paths: list[Path]) -> None:
        assert {path.stem for path in fragment_paths} <= set(plugin_order())

    def test_every_hook_file_wraps_its_events_in_hooks(self) -> None:
        documents = [json.loads(path.read_text()) for path in hook_files(plugin_root=PLUGIN_ROOT)]
        assert all("hooks" in document for document in documents)

    def test_manifest_lists_every_fragment_in_plugin_order(
        self,
        manifest: dict[str, Any],
    ) -> None:
        fragments = hook_files(plugin_root=PLUGIN_ROOT)[1:]
        expected = [f"./{path.relative_to(PLUGIN_ROOT).as_posix()}" for path in fragments]
        assert manifest["hooks"] == expected

    def test_manifest_omits_the_default_hooks_file(self, manifest: dict[str, Any]) -> None:
        assert "./hooks/hooks.json" not in manifest["hooks"]
