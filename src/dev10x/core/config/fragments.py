"""Config fragments keyed by future plugin (ADR-0034 Stage A3, GH-1551).

Shared configuration is split into one fragment per plugin named in
``dev10x/core/plugins.yaml``. A fragment is a YAML mapping stored as
``<plugin>.yaml`` in any of several fragment directories; every
fragment is still loaded by the single ``dev10x`` plugin, so merging
them must reproduce exactly what the one-file original declared.

Merge order is ``core`` first, then the order ``plugins.yaml`` lists
the plugins, then directory order. Lists concatenate in that order,
mappings merge key by key, and two fragments that disagree on a scalar
are an error rather than a silent last-writer-wins.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dev10x.core.plugin_map import PLUGIN_MAP_PATH, load_plugin_map

CORE_PLUGIN = "core"
FRAGMENT_SUFFIX = ".yaml"


class FragmentError(ValueError):
    pass


@dataclass(frozen=True)
class ConfigFragment:
    plugin: str
    path: Path


def plugin_order(*, plugin_map_path: Path = PLUGIN_MAP_PATH) -> tuple[str, ...]:
    names = tuple(load_plugin_map(path=plugin_map_path).plugins)
    return (CORE_PLUGIN, *(name for name in names if name != CORE_PLUGIN))


def discover_fragments(
    *,
    directories: Iterable[Path],
    plugins: Sequence[str],
    suffix: str = FRAGMENT_SUFFIX,
) -> list[ConfigFragment]:
    found: list[ConfigFragment] = []
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{suffix}")):
            if path.stem not in plugins:
                raise FragmentError(
                    f"{path}: a fragment must be named after a plugin ({', '.join(plugins)})"
                )
            found.append(ConfigFragment(plugin=path.stem, path=path))
    rank = {plugin: index for index, plugin in enumerate(plugins)}
    return sorted(found, key=lambda fragment: rank[fragment.plugin])


def load_fragment(*, path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FragmentError(f"{path}: a fragment must be a YAML mapping")
    return data


def merge_documents(*, documents: Sequence[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source, document in documents:
        _merge_into(target=merged, incoming=document, source=source, location=())
    return merged


def load_merged(
    *,
    fragments: Sequence[ConfigFragment],
    base: tuple[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    documents = [] if base is None else [base]
    documents.extend(
        (str(fragment.path), load_fragment(path=fragment.path)) for fragment in fragments
    )
    return merge_documents(documents=documents)


def _merge_into(
    *,
    target: dict[str, Any],
    incoming: Mapping[str, Any],
    source: str,
    location: tuple[str, ...],
) -> None:
    for key, value in incoming.items():
        if key not in target:
            target[key] = copy.deepcopy(value)
            continue
        current = target[key]
        if isinstance(current, list) and isinstance(value, list):
            current.extend(copy.deepcopy(value))
        elif isinstance(current, dict) and isinstance(value, dict):
            _merge_into(target=current, incoming=value, source=source, location=(*location, key))
        elif current != value:
            dotted = ".".join((*location, str(key)))
            raise FragmentError(f"{source}: `{dotted}` conflicts with an earlier fragment")


__all__ = [
    "CORE_PLUGIN",
    "FRAGMENT_SUFFIX",
    "ConfigFragment",
    "FragmentError",
    "discover_fragments",
    "load_fragment",
    "load_merged",
    "merge_documents",
    "plugin_order",
]
