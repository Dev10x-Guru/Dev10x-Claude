"""Resolve which knowledge vault `dev10x:reflect` writes into (GH-1822).

The vault is user configuration, never a path baked into the plugin: one
person files lessons into an Obsidian vault on a synced drive, another
keeps a plain Markdown folder per client, and most installs have no vault
at all. `<Dev10x config>/knowledge-vault.yaml` carries top-level defaults
and a repo-addressed ``projects:`` list (ADR-0026 ``match_repo:``) whose
first matching entry overrides them, so lessons from client repos can land
in that client's folder.

An absent file, an absent ``vault:`` key, or ``enabled: false`` are all
answers, not errors: reflection is optional, and the skill reports the
one-line reason and moves on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.project_match import MatchScheme, ProjectsStatus, evaluate_projects

DEFAULT_INDEX_NOTE = "index.md"
DEFAULT_LOG_NOTE = "log.md"
DEFAULT_FOLDERS: dict[str, str] = {
    "retro": "Retros",
    "platform": "Platform",
    "process": "Process",
    "patterns": "Patterns",
}

_MERGED_MAPPINGS = ("folders",)


@dataclass(frozen=True)
class VaultConfig:
    """The resolved vault for one checkout."""

    source: str
    configured: bool
    reason: str = ""
    vault: Path | None = None
    folders: dict[str, str] = field(default_factory=dict)
    index_note: str = DEFAULT_INDEX_NOTE
    log_note: str = DEFAULT_LOG_NOTE
    rules_note: Path | None = None
    repo: str | None = None
    project_status: str = ProjectsStatus.ABSENT.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "reason": self.reason,
            "source": self.source,
            "vault": str(self.vault) if self.vault else None,
            "folders": dict(self.folders),
            "index_note": self.index_note,
            "log_note": self.log_note,
            "rules_note": str(self.rules_note) if self.rules_note else None,
            "repo": self.repo,
            "project_status": self.project_status,
        }


def _merge(*, base: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    merged = {**base, **{k: v for k, v in entry.items() if k != "match_repo"}}
    for key in _MERGED_MAPPINGS:
        base_map, entry_map = base.get(key), entry.get(key)
        if isinstance(base_map, dict) and isinstance(entry_map, dict):
            merged[key] = {**base_map, **entry_map}
    return merged


def _select_entry(
    *,
    document: dict[str, Any],
    source: str,
    repo: str | None,
    repo_reason: str | None,
) -> tuple[dict[str, Any], str]:
    report = evaluate_projects(
        document,
        scheme=MatchScheme.REPO,
        source=source,
        target=repo,
        unresolved_reason=repo_reason,
    )
    index = report.matched_index
    if index is None:
        return {}, report.status.value
    return document["projects"][index], report.status.value


def _load_document(*, path: Path) -> Result[dict[str, Any]]:
    """Read once; an empty or comment-only file is an empty mapping."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return err(f"cannot read {path}: {exc}")
    except yaml.YAMLError as exc:
        return err(f"cannot parse {path}: {exc}")
    if document is None:
        return ok({})
    if not isinstance(document, dict):
        return err(f"{path}: the top level must be a mapping")
    return ok(document)


def _expand(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def _folders(raw: Any) -> Result[dict[str, str]]:
    folders = dict(DEFAULT_FOLDERS)
    if raw is None:
        return ok(folders)
    if not isinstance(raw, dict):
        return err("`folders:` must be a mapping of lesson kind to vault-relative folder")
    for kind, folder in raw.items():
        if not isinstance(folder, str) or not folder.strip():
            return err(f"`folders.{kind}` must be a non-empty vault-relative path")
        confined = confine(vault=Path("/vault"), relative=folder)
        if not isinstance(confined, SuccessResult):
            return err(f"`folders.{kind}`: {confined.error}")
        folders[str(kind)] = folder.strip().strip("/")
    return ok(folders)


def confine(*, vault: Path, relative: str) -> Result[Path]:
    """Join ``relative`` onto ``vault``, refusing anything that escapes it.

    A vault-relative folder or note name comes from config or from the
    agent's own arguments; neither may write outside the vault. Absolute
    paths and ``..`` traversal are rejected before the filesystem is
    touched, and the resolved result is re-checked so a symlink inside the
    vault cannot point the write somewhere else.
    """
    candidate = Path(relative)
    if candidate.is_absolute():
        return err(f"{relative!r} must be relative to the vault, not absolute")
    if ".." in candidate.parts:
        return err(f"{relative!r} must not contain '..'")
    joined = vault / candidate
    resolved_vault = vault.resolve()
    resolved = joined.resolve()
    if resolved != resolved_vault and resolved_vault not in resolved.parents:
        return err(f"{relative!r} resolves outside the vault ({resolved})")
    return ok(joined)


def resolve_vault_config(
    *,
    repo: str | None,
    repo_reason: str | None = None,
    path: Path | None = None,
) -> Result[VaultConfig]:
    """Resolve the vault for a checkout whose ``nameWithOwner`` is ``repo``.

    Returns ``ok`` with ``configured=False`` and a reason when there is
    nothing to write into; returns ``err`` when the file cannot be read or
    parsed, or says something that cannot be honored (a malformed key, a
    vault that does not exist), because silently skipping would hide a
    typo.
    """
    config_path = path or Dev10xConfigDir.knowledge_vault_yaml()
    source = str(config_path)
    if not config_path.is_file():
        return ok(
            VaultConfig(
                source=source,
                configured=False,
                reason=f"no knowledge vault configured ({source} does not exist)",
                repo=repo,
            )
        )
    loaded = _load_document(path=config_path)
    if not isinstance(loaded, SuccessResult):
        return err(loaded.error, source=source)
    document = loaded.value
    entry, status = _select_entry(
        document=document, source=source, repo=repo, repo_reason=repo_reason
    )
    settings = _merge(base=document, entry=entry)
    settings.pop("projects", None)

    if settings.get("enabled", True) is False:
        return ok(
            VaultConfig(
                source=source,
                configured=False,
                reason="reflection disabled (`enabled: false`) for this repo",
                repo=repo,
                project_status=status,
            )
        )
    raw_vault = settings.get("vault")
    if not raw_vault:
        return ok(
            VaultConfig(
                source=source,
                configured=False,
                reason=f"no `vault:` set in {source}",
                repo=repo,
                project_status=status,
            )
        )
    if not isinstance(raw_vault, str):
        return err("`vault:` must be a path string", source=source)
    vault = _expand(raw_vault)
    if not vault.is_absolute():
        return err(
            f"`vault:` must be absolute after ~ expansion, got {raw_vault!r}", source=source
        )
    if not vault.is_dir():
        return err(f"vault {vault} does not exist or is not a directory", source=source)

    folders = _folders(settings.get("folders"))
    if not isinstance(folders, SuccessResult):
        return err(folders.error, source=source)

    names: dict[str, str] = {}
    for key, default in (("index_note", DEFAULT_INDEX_NOTE), ("log_note", DEFAULT_LOG_NOTE)):
        value = settings.get(key, default)
        if not isinstance(value, str) or "/" in value or not value.endswith(".md"):
            return err(f"`{key}:` must be a bare Markdown file name, got {value!r}", source=source)
        names[key] = value

    rules_note: Path | None = None
    raw_rules = settings.get("rules_note")
    if raw_rules:
        confined = confine(vault=vault, relative=str(raw_rules))
        if not isinstance(confined, SuccessResult):
            return err(f"`rules_note:` {confined.error}", source=source)
        rules_note = confined.value

    return ok(
        VaultConfig(
            source=source,
            configured=True,
            vault=vault,
            folders=folders.value,
            index_note=names["index_note"],
            log_note=names["log_note"],
            rules_note=rules_note,
            repo=repo,
            project_status=status,
        )
    )
