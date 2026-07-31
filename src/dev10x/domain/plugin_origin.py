"""Resolve which plugin — and which issue tracker — owns a skill (GH-816).

Every installed plugin's skills live under ``~/.claude/plugins/``,
regardless of which marketplace shipped them. A ``Dev10x:skill-audit``
finding about a *non-Dev10x* plugin's skill therefore looks identical,
by path, to a finding about a Dev10x skill — so Phase 7 used to file it
at the Dev10x tracker (wrong maintainer) or drop it entirely.

This module maps a skill path back to its owning plugin and that
plugin's source repository, so the audit flow can confirm the filing
destination instead of assuming it.

Two install layouts are recognised under the plugins root:

* ``cache/<marketplace>/<plugin>/<version>/skills/<skill>/SKILL.md``
* ``marketplaces/<marketplace>/<plugin>/skills/<skill>/SKILL.md``

The marketplace segment is looked up in ``known_marketplaces.json``,
whose entries carry either a GitHub ``source.repo`` (``owner/name``) or
a git ``source.url``. A missing or malformed entry is reported as an
unresolved origin — never silently defaulted to Dev10x.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.result import Result, SuccessResult, err, ok

_CACHE_ROOT = "cache"
_MARKETPLACE_ROOT = "marketplaces"

_SSH_REMOTE = re.compile(r"^(?:ssh://)?git@[^:/]+[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$")
_HTTPS_REMOTE = re.compile(r"^https?://[^/]+/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$")


@dataclass(frozen=True)
class PluginOrigin:
    """The plugin that owns a skill, and where its issues belong."""

    marketplace: str
    plugin: str
    version: str | None
    repo: str | None
    source_kind: str
    source_url: str | None
    plugin_dir: str

    @property
    def issue_tracker(self) -> str | None:
        return f"https://github.com/{self.repo}/issues" if self.repo else None

    @property
    def is_dev10x(self) -> bool:
        return (self.repo or "").lower() == "dev10x-guru/dev10x-claude"

    def to_dict(self) -> dict[str, Any]:
        return {
            "marketplace": self.marketplace,
            "plugin": self.plugin,
            "version": self.version,
            "repo": self.repo,
            "source_kind": self.source_kind,
            "source_url": self.source_url,
            "plugin_dir": self.plugin_dir,
            "issue_tracker": self.issue_tracker,
            "is_dev10x": self.is_dev10x,
        }


def repo_from_url(*, url: str) -> str | None:
    """Extract ``owner/name`` from an SSH or HTTPS git remote URL."""
    for pattern in (_SSH_REMOTE, _HTTPS_REMOTE):
        match = pattern.match(url.strip())
        if match:
            return match.group("repo")
    return None


def load_marketplace_sources(
    *,
    marketplaces_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Read ``known_marketplaces.json`` into ``{name: source}``.

    A missing or unparseable catalog yields an empty mapping — callers
    then report every origin as tracker-unresolved rather than failing
    the whole audit.
    """
    path = marketplaces_path or ClaudeDir.known_marketplaces_json()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    sources: dict[str, dict[str, Any]] = {}
    for name, entry in raw.items():
        if isinstance(entry, dict) and isinstance(entry.get("source"), dict):
            sources[name] = entry["source"]
    return sources


def _repo_and_kind(*, source: dict[str, Any] | None) -> tuple[str | None, str, str | None]:
    if not source:
        return None, "unknown", None

    kind = str(source.get("source") or "unknown")
    repo = source.get("repo")
    if isinstance(repo, str) and "/" in repo:
        return repo, kind, None

    url = source.get("url")
    if isinstance(url, str) and url:
        return repo_from_url(url=url), kind, url

    return None, kind, None


def _split_plugin_segments(*, parts: tuple[str, ...]) -> tuple[str, str, str | None] | None:
    """Map plugins-root-relative parts to ``(marketplace, plugin, version)``."""
    if len(parts) < 3:
        return None

    root, marketplace, plugin = parts[0], parts[1], parts[2]
    if root == _CACHE_ROOT:
        version = parts[3] if len(parts) > 3 else None
        return marketplace, plugin, version
    if root == _MARKETPLACE_ROOT:
        return marketplace, plugin, None
    return None


def resolve_plugin_origin(
    *,
    skill_path: str | Path,
    plugins_root: Path | None = None,
    marketplace_sources: dict[str, dict[str, Any]] | None = None,
) -> Result[PluginOrigin]:
    """Resolve the plugin owning ``skill_path``.

    Returns an error Result when the path lies outside the plugins root
    or is too short to name a plugin. A path that *is* under a plugin
    but whose marketplace has no catalog entry still resolves — with
    ``repo=None`` — so the caller can surface "origin known, tracker
    unknown" instead of guessing Dev10x.
    """
    root = (plugins_root or ClaudeDir.plugins_dir()).expanduser()
    candidate = Path(skill_path).expanduser()

    if not candidate.is_absolute():
        return err(f"skill path is not absolute: {skill_path}", skill_path=str(skill_path))

    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return err(
            f"skill path is not under the plugins root: {candidate}",
            skill_path=str(candidate),
            plugins_root=str(root),
        )

    segments = _split_plugin_segments(parts=relative.parts)
    if segments is None:
        return err(
            f"skill path does not name a plugin: {candidate}",
            skill_path=str(candidate),
            plugins_root=str(root),
        )

    marketplace, plugin, version = segments
    sources = (
        marketplace_sources
        if marketplace_sources is not None
        else load_marketplace_sources(marketplaces_path=root / "known_marketplaces.json")
    )
    repo, source_kind, source_url = _repo_and_kind(source=sources.get(marketplace))

    plugin_parts = [relative.parts[0], marketplace, plugin]
    if version:
        plugin_parts.append(version)

    return ok(
        PluginOrigin(
            marketplace=marketplace,
            plugin=plugin,
            version=version,
            repo=repo,
            source_kind=source_kind,
            source_url=source_url,
            plugin_dir=str(root.joinpath(*plugin_parts)),
        )
    )


def resolve_skill_origins(
    *,
    skill_paths: list[str],
    plugins_root: Path | None = None,
) -> Result[dict[str, Any]]:
    """Group audit findings' skill paths by their owning plugin repo.

    The MCP-facing entry point for skill-audit Phase 7: it returns one
    ``targets`` entry per distinct destination so the confirmation gate
    can list every repo a batch of findings would reach, plus an
    ``unresolved`` list for paths with no derivable tracker.
    """
    if not skill_paths:
        return err("no skill paths provided")

    root = (plugins_root or ClaudeDir.plugins_dir()).expanduser()
    sources = load_marketplace_sources(marketplaces_path=root / "known_marketplaces.json")

    targets: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []

    for skill_path in skill_paths:
        result = resolve_plugin_origin(
            skill_path=skill_path,
            plugins_root=root,
            marketplace_sources=sources,
        )
        if not isinstance(result, SuccessResult):
            unresolved.append({"skill_path": skill_path, "reason": result.error})
            continue

        origin = result.value
        if origin.repo is None:
            unresolved.append(
                {
                    "skill_path": skill_path,
                    "reason": (
                        f"marketplace '{origin.marketplace}' has no resolvable "
                        "source repo in known_marketplaces.json"
                    ),
                    "origin": origin.to_dict(),
                }
            )
            continue

        target = targets.setdefault(
            origin.repo,
            {**origin.to_dict(), "skill_paths": []},
        )
        target["skill_paths"].append(skill_path)

    return ok(
        {
            "targets": list(targets.values()),
            "unresolved": unresolved,
            "target_count": len(targets),
            "unresolved_count": len(unresolved),
        }
    )


__all__ = [
    "PluginOrigin",
    "load_marketplace_sources",
    "repo_from_url",
    "resolve_plugin_origin",
    "resolve_skill_origins",
]
