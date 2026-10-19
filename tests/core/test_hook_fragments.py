"""GH-1556: hook registrations read from hooks.json plus per-plugin fragments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dev10x.core.config.fragments import ConfigFragment, FragmentError, discover_fragments
from dev10x.core.config.hook_fragments import hook_files, merged_hook_entries


def _hook_document(*, event: str, matcher: str, command: str, timeout: int) -> dict[str, Any]:
    hook = {"type": "command", "command": command, "timeout": timeout}
    return {"hooks": {event: [{"matcher": matcher, "hooks": [hook]}]}}


def _write_json(*, path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    _write_json(
        path=tmp_path / "hooks" / "hooks.json",
        document=_hook_document(event="PreToolUse", matcher="Bash", command="base", timeout=10),
    )
    return tmp_path


@pytest.fixture
def split_root(plugin_root: Path) -> Path:
    fragments_dir = plugin_root / "hooks" / "hooks.d"
    _write_json(
        path=fragments_dir / "coding.json",
        document=_hook_document(event="PostToolUse", matcher="Edit", command="fmt", timeout=5),
    )
    _write_json(
        path=fragments_dir / "qa.json",
        document=_hook_document(event="Stop", matcher="*", command="qa", timeout=3),
    )
    _write_json(
        path=fragments_dir / "core.json",
        document=_hook_document(event="PreToolUse", matcher="Bash", command="base", timeout=10),
    )
    return plugin_root


@pytest.fixture
def split_files(split_root: Path) -> list[Path]:
    return hook_files(plugin_root=split_root)


@pytest.fixture
def split_entries(split_root: Path) -> set[tuple[str, str, str, int]]:
    return merged_hook_entries(plugin_root=split_root)


class TestDiscoverFragmentsSuffix:
    def test_finds_only_the_requested_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "core.json").write_text("{}")
        (tmp_path / "qa.yaml").write_text("{}")
        found = discover_fragments(directories=[tmp_path], plugins=("core", "qa"), suffix=".json")
        assert found == [ConfigFragment(plugin="core", path=tmp_path / "core.json")]


class TestHookFiles:
    def test_lists_only_hooks_json_without_fragments(self, plugin_root: Path) -> None:
        assert hook_files(plugin_root=plugin_root) == [plugin_root / "hooks" / "hooks.json"]

    def test_lists_hooks_json_then_fragments_in_plugin_order(
        self,
        split_root: Path,
        split_files: list[Path],
    ) -> None:
        fragments_dir = split_root / "hooks" / "hooks.d"
        assert split_files == [
            split_root / "hooks" / "hooks.json",
            fragments_dir / "core.json",
            fragments_dir / "qa.json",
            fragments_dir / "coding.json",
        ]

    def test_refuses_a_fragment_named_after_no_plugin(self, plugin_root: Path) -> None:
        _write_json(path=plugin_root / "hooks" / "hooks.d" / "stray.json", document={"hooks": {}})
        with pytest.raises(FragmentError, match="named after a plugin"):
            hook_files(plugin_root=plugin_root)


class TestMergedHookEntries:
    def test_unions_entries_across_files(
        self,
        split_entries: set[tuple[str, str, str, int]],
    ) -> None:
        assert split_entries == {
            ("PreToolUse", "Bash", "base", 10),
            ("PostToolUse", "Edit", "fmt", 5),
            ("Stop", "*", "qa", 3),
        }

    def test_defaults_a_missing_matcher_and_timeout(self, tmp_path: Path) -> None:
        _write_json(
            path=tmp_path / "hooks" / "hooks.json",
            document={"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bye"}]}]}},
        )
        assert merged_hook_entries(plugin_root=tmp_path) == {("Stop", "", "bye", 0)}

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"PreToolUse": []}, id="bare-events"),
            pytest.param([], id="not-a-mapping"),
        ],
    )
    def test_refuses_a_file_without_a_hooks_wrapper(
        self,
        plugin_root: Path,
        document: Any,
    ) -> None:
        _write_json(path=plugin_root / "hooks" / "hooks.d" / "qa.json", document=document)
        with pytest.raises(FragmentError, match="top-level `hooks` key"):
            merged_hook_entries(plugin_root=plugin_root)
