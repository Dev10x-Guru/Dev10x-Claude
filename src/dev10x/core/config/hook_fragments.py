"""Hook registrations split by future plugin (ADR-0034 Stage A3, GH-1556).

``hooks/hooks.json`` holds the core entries and is loaded by the harness
by default; each plugin's entries live in ``hooks/hooks.d/<plugin>.json``,
which ``.claude-plugin/plugin.json`` lists under ``hooks`` so the harness
merges them in. Reading every file together proves the split lossless.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dev10x.core.config.fragments import FragmentError, discover_fragments, plugin_order

HOOKS_FILE = Path("hooks") / "hooks.json"
HOOK_FRAGMENTS_DIR = Path("hooks") / "hooks.d"
HOOK_FRAGMENT_SUFFIX = ".json"

HookEntry = tuple[str, str, str, int]


def hook_files(*, plugin_root: Path) -> list[Path]:
    fragments = discover_fragments(
        directories=[plugin_root / HOOK_FRAGMENTS_DIR],
        plugins=plugin_order(),
        suffix=HOOK_FRAGMENT_SUFFIX,
    )
    return [plugin_root / HOOKS_FILE, *(fragment.path for fragment in fragments)]


def merged_hook_entries(*, plugin_root: Path) -> set[HookEntry]:
    entries: set[HookEntry] = set()
    for path in hook_files(plugin_root=plugin_root):
        entries |= _entries(path=path)
    return entries


def _entries(*, path: Path) -> set[HookEntry]:
    document: Any = json.loads(path.read_text())
    if not isinstance(document, dict) or "hooks" not in document:
        raise FragmentError(f"{path}: a hook file must wrap its events in a top-level `hooks` key")
    return {
        (event, group.get("matcher", ""), hook["command"], hook.get("timeout", 0))
        for event, groups in document["hooks"].items()
        for group in groups
        for hook in group["hooks"]
    }


__all__ = [
    "HOOKS_FILE",
    "HOOK_FRAGMENTS_DIR",
    "HOOK_FRAGMENT_SUFFIX",
    "HookEntry",
    "hook_files",
    "merged_hook_entries",
]
