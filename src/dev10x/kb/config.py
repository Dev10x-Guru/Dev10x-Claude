"""Where harvested lessons land in the knowledge vault (GH-1985).

The vault itself is the one `dev10x-tasks:reflect` uses
(`knowledge-vault.yaml`, see `dev10x.core.domain.knowledge_vault`). The
harvest adds a top-level ``kb:`` mapping naming each optional place:

```yaml
kb:
  hub: Sources/Harvested.md          # one row per source, ever
  topics: Sources/Topics             # one living page per topic
  people: People                     # one note per speaker or author
  strategy_hub: Projects/Strategy.md # links topic pages flagged `strategy`
  transcribe_model: small            # whisper model for podcast audio
```

Every place is optional: an unset key turns its step off, so a vault
with only ``vault:`` still gets daily-note attachments and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.core.domain.common.config_io import ConfigIOError, load_yaml
from dev10x.core.domain.common.result import Result, SuccessResult, err, ok
from dev10x.core.domain.dev10x_paths import Dev10xConfigDir
from dev10x.core.domain.knowledge_vault import VaultConfig, confine, resolve_vault_config
from dev10x.kb.spotify import DEFAULT_MODEL

_NOTE_KEYS = ("hub", "strategy_hub")
_FOLDER_KEYS = ("topics", "people")


@dataclass(frozen=True)
class KbConfig:
    vault: VaultConfig
    hub: Path | None = None
    topics: Path | None = None
    people: Path | None = None
    strategy_hub: Path | None = None
    transcribe_model: str = DEFAULT_MODEL

    @property
    def configured(self) -> bool:
        return self.vault.configured and self.vault.vault is not None

    def to_dict(self) -> dict[str, Any]:
        def text(path: Path | None) -> str | None:
            return str(path) if path else None

        return {
            "configured": self.configured,
            "reason": self.vault.reason,
            "source": self.vault.source,
            "vault": text(self.vault.vault),
            "rules_note": text(self.vault.rules_note),
            "hub": text(self.hub),
            "topics": text(self.topics),
            "people": text(self.people),
            "strategy_hub": text(self.strategy_hub),
            "transcribe_model": self.transcribe_model,
        }


def _section(path: Path) -> Result[dict[str, Any]]:
    try:
        document = load_yaml(path, strict=True)
    except ConfigIOError as exc:
        return err(str(exc), source=str(path))
    section = document.get("kb") or {}
    if not isinstance(section, dict):
        return err("`kb:` must be a mapping", source=str(path))
    return ok(section)


def resolve_kb_config(
    *,
    repo: str | None,
    repo_reason: str | None = None,
    path: Path | None = None,
) -> Result[KbConfig]:
    config_path = path or Dev10xConfigDir.knowledge_vault_yaml()
    vault = resolve_vault_config(repo=repo, repo_reason=repo_reason, path=config_path)
    if not isinstance(vault, SuccessResult):
        return vault
    if not vault.value.configured or vault.value.vault is None:
        return ok(KbConfig(vault=vault.value))
    section = _section(config_path)
    if not isinstance(section, SuccessResult):
        return section
    places: dict[str, Path] = {}
    for key in (*_NOTE_KEYS, *_FOLDER_KEYS):
        raw = section.value.get(key)
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw.strip():
            return err(f"`kb.{key}` must be a non-empty vault-relative path")
        if key in _NOTE_KEYS and not raw.endswith(".md"):
            return err(f"`kb.{key}` must name a Markdown note, got {raw!r}")
        confined = confine(vault=vault.value.vault, relative=raw.strip().rstrip("/"))
        if not isinstance(confined, SuccessResult):
            return err(f"`kb.{key}`: {confined.error}")
        places[key] = confined.value
    model = section.value.get("transcribe_model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model.strip():
        return err("`kb.transcribe_model` must be a whisper model name, e.g. small")
    return ok(KbConfig(vault=vault.value, transcribe_model=model.strip(), **places))
