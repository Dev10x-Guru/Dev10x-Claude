"""Copy a fetched record next to the note that cites it (GH-1985).

The work directory is cleared on reboot, so a note that links there
ends up with dead links. Persisting copies the text and the metadata
into the note's attachment folder under a human-readable name.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from dev10x.core.domain.common.result import Result, SuccessResult, err, ok
from dev10x.kb.config import KbConfig
from dev10x.kb.record import SourceKind, first_symlink, read_meta, workdir

log = logging.getLogger(__name__)

_UNSAFE_NAME = re.compile(r"[\\/:*?\"<>|#\[\]\x00-\x1f\x7f]")
MAX_NAME_LENGTH = 150
_TEXT_SUFFIX = {
    SourceKind.YOUTUBE: "transcript.txt",
    SourceKind.SPOTIFY: "transcript.txt",
    SourceKind.WEB: "article.md",
}


@dataclass(frozen=True)
class PersistedFiles:
    text: Path
    meta: Path

    def to_dict(self) -> dict[str, str]:
        return {"text": str(self.text), "meta": str(self.meta)}


def validate_name(name: str) -> Result[str]:
    """A ``Speaker - Title`` attachment name that is safe as a file name."""
    cleaned = " ".join(name.split())
    if not cleaned or cleaned.startswith("."):
        return err("attachment name must be non-empty and not start with '.'")
    if _UNSAFE_NAME.search(cleaned):
        return err(f"attachment name {name!r} contains a path, link or control character")
    if len(cleaned) > MAX_NAME_LENGTH:
        return err(f"attachment name is longer than {MAX_NAME_LENGTH} characters")
    return ok(cleaned)


def inside_vault(*, config: KbConfig, path: Path) -> Result[Path]:
    vault = config.vault.vault
    if not config.configured or vault is None:
        return err(config.vault.reason or "no knowledge vault configured")
    if not path.is_absolute():
        return err(f"{path} must be an absolute path inside the vault")
    root = vault.resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        return err(f"{path} is outside the vault {vault}")
    return ok(path)


def persist_record(
    *,
    config: KbConfig,
    source_id: str,
    attachments: Path,
    name: str,
    directory: Path | None = None,
) -> Result[PersistedFiles]:
    checked_name = validate_name(name)
    if not isinstance(checked_name, SuccessResult):
        return checked_name
    target = inside_vault(config=config, path=attachments)
    if not isinstance(target, SuccessResult):
        return target
    meta = read_meta(source_id=source_id, directory=directory)
    if not isinstance(meta, SuccessResult):
        return meta
    raw_kind = meta.value.get("kind", SourceKind.WEB.value)
    try:
        kind = SourceKind(raw_kind)
    except ValueError:
        return err(f"record {source_id} has an unknown kind {raw_kind!r}; fetch it again")
    source = directory or workdir()
    text_path = attachments / f"{checked_name.value} - {_TEXT_SUFFIX[kind]}"
    meta_path = attachments / f"{checked_name.value} - meta.txt"
    source_text = source / f"{source_id}.txt"
    linked = first_symlink(source_text, text_path, meta_path)
    if linked:
        return err(f"{linked} is a symlink; refusing to copy through it")
    try:
        attachments.mkdir(parents=True, exist_ok=True)
        text_path.write_bytes(source_text.read_bytes())
        meta_path.write_bytes((source / f"{source_id}.meta.txt").read_bytes())
    except OSError as exc:
        log.error("persist failed", extra={"id": source_id, "error": str(exc)})
        return err(f"cannot persist {source_id} into {attachments}: {exc}")
    return ok(PersistedFiles(text=text_path, meta=meta_path))
