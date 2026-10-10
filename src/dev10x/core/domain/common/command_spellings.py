"""One catalog entry, every spelling of the command (GH-1317).

A CLI command reachable by several literal spellings — ``dev10x <sub>``,
``uvx dev10x <sub>``, ``uv run dev10x <sub>`` — needed one hand-written
allow-rule per spelling, because Claude Code's rule matching is literal.
Coverage therefore depended on whoever added the entry remembering all of
them, and ``dev10x permission ensure-base --dry-run`` prompted for years
because only the ``uvx`` spelling was catalogued.

``command_spellings:`` declares the command once and renders a rule per
spelling. Two shapes, one renderer:

- ``prefixes:`` × ``commands:`` for a command reached through different
  runners (the ``dev10x`` CLI);
- ``commands:`` alone for a capability whose spellings are distinct
  binaries (ImageMagick's ``magick`` / ``convert`` / ``montage``).

The expansion is a **source-shape** change only. Every entry renders into
the same flat rule strings the catalogs already carry, and the key is
consumed at the load seam — so merge, drift, gap and coverage readers see
an ordinary catalog and a userspace copy predating this schema keeps
merging exactly as before.
"""

from __future__ import annotations

from typing import Any

SPELLINGS_KEY = "command_spellings"
ALLOW_KEY = "base_permissions"
RULES_KEY = "rules"


def render_spelling_rules(*, entries: object) -> list[str]:
    """Render ``Bash(<prefix><command>:*)`` for every prefix × command pair.

    Malformed entries contribute nothing rather than raising: a catalog is
    read by diagnostics that must degrade to "fewer rules", never to a
    traceback that reads as infrastructure noise.
    """
    if not isinstance(entries, list):
        return []
    rules: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        commands = [
            command.strip() for command in _str_list(entry.get("commands")) if command.strip()
        ]
        prefixes = _str_list(entry.get("prefixes")) or [""]
        for command in commands:
            for prefix in prefixes:
                rule = f"Bash({prefix}{command}:*)"
                if rule not in rules:
                    rules.append(rule)
    return rules


def expand_spellings(data: Any) -> Any:
    """Fold every ``command_spellings:`` block into its rule list.

    Handles both catalog shapes in one pass — the flat
    ``projects.yaml`` (top-level key folding into ``base_permissions``)
    and the grouped ``baseline-permissions.yaml`` (per-group key folding
    into that group's ``rules``). Returns ``data`` untouched when no block
    is present, so every caller can route through it unconditionally.
    """
    if not isinstance(data, dict):
        return data
    return _expand_groups(data=_expand_flat(data=data))


def _expand_flat(*, data: dict) -> dict:
    if SPELLINGS_KEY not in data:
        return data
    expanded = dict(data)
    entries = expanded.pop(SPELLINGS_KEY)
    expanded[ALLOW_KEY] = _appended(
        existing=expanded.get(ALLOW_KEY),
        rendered=render_spelling_rules(entries=entries),
    )
    return expanded


def _expand_groups(*, data: dict) -> dict:
    groups = data.get("groups")
    if not isinstance(groups, dict):
        return data
    if not any(isinstance(group, dict) and SPELLINGS_KEY in group for group in groups.values()):
        return data
    expanded = dict(data)
    expanded["groups"] = {
        name: _expand_group(group=group) if isinstance(group, dict) else group
        for name, group in groups.items()
    }
    return expanded


def _expand_group(*, group: dict) -> dict:
    if SPELLINGS_KEY not in group:
        return group
    merged = dict(group)
    entries = merged.pop(SPELLINGS_KEY)
    merged[RULES_KEY] = _appended(
        existing=merged.get(RULES_KEY),
        rendered=render_spelling_rules(entries=entries),
    )
    return merged


def _appended(*, existing: object, rendered: list[str]) -> list:
    current = list(existing) if isinstance(existing, list) else []
    return [*current, *(rule for rule in rendered if rule not in current)]


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


__all__ = [
    "ALLOW_KEY",
    "RULES_KEY",
    "SPELLINGS_KEY",
    "expand_spellings",
    "render_spelling_rules",
]
