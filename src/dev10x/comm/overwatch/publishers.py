"""Where a session can share an artifact (GH-1938, ADR-0036 D6).

The built-in claude.ai publisher, plus `artifact_publishers:` from
``~/.config/Dev10x/overwatch.yaml``. Overwatch never calls a publisher;
it only words the request the owning session carries out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dev10x.comm.overwatch.artifacts import SLUG
from dev10x.domain.dev10x_paths import Dev10xConfigDir

PUBLISHERS_KEY = "artifact_publishers"
KINDS = ("skill", "mcp", "prompt")


@dataclass(frozen=True)
class Publisher:
    id: str
    label: str
    kind: str
    target: str
    instruction_text: str = ""

    def instruction(self, *, path: str, artifact_id: str, title: str) -> str:
        if self.instruction_text:
            text = self.instruction_text
        elif self.kind == "skill":
            text = f"Run Skill({self.target}) to publish it"
        elif self.kind == "mcp":
            text = f"Call {self.target} to publish it"
        else:
            text = (
                self.target.replace("{path}", path)
                .replace("{id}", artifact_id)
                .replace("{title}", " ".join(title.split()))
            )
        return text.strip().rstrip(".")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label}


CLAUDE_AI = Publisher(
    id="claude-ai",
    label="claude.ai",
    kind="skill",
    target="dev10x:artifact",
    instruction_text=(
        "Use the export path of dev10x:artifact to publish it as a claude.ai Artifact"
    ),
)


@dataclass(frozen=True)
class PublisherConfig:
    publishers: list[Publisher] = field(default_factory=lambda: [CLAUDE_AI])
    errors: list[str] = field(default_factory=list)

    def find(self, *, publisher_id: str) -> Publisher | None:
        return next((item for item in self.publishers if item.id == publisher_id), None)


def builtin_publishers() -> PublisherConfig:
    return PublisherConfig()


def _entry(*, raw: object, where: str, taken: set[str]) -> Publisher | str:
    if not isinstance(raw, dict):
        return f"{where}: must be a mapping"
    publisher_id = raw.get("id")
    if not isinstance(publisher_id, str) or not SLUG.fullmatch(publisher_id):
        return f"{where}.id: must be a slug"
    if publisher_id in taken:
        return f"{where}.id: duplicate publisher id {publisher_id!r}"
    values = {key: raw.get(key) for key in ("label", "target")}
    for key, value in values.items():
        if not isinstance(value, str) or not value.strip():
            return f"{where}.{key}: must be a non-empty string"
    if raw.get("kind") not in KINDS:
        return f"{where}.kind: must be one of {', '.join(KINDS)}"
    return Publisher(
        id=publisher_id,
        label=str(values["label"]),
        kind=str(raw["kind"]),
        target=str(values["target"]),
    )


def _document(*, path: Path) -> dict[str, Any] | str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        return f"{path} is unreadable: {exc}"
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return f"{path} is not valid YAML: {exc}"
    return doc if isinstance(doc, dict) else f"{path} must hold a mapping"


def load_publishers(*, path: Path | None = None) -> PublisherConfig:
    doc = _document(path=path or Dev10xConfigDir.overwatch_yaml())
    if isinstance(doc, str):
        return PublisherConfig(errors=[doc])
    entries = doc.get(PUBLISHERS_KEY) or []
    if not isinstance(entries, list):
        return PublisherConfig(errors=[f"{PUBLISHERS_KEY}: must be a list"])
    publishers = [CLAUDE_AI]
    errors = []
    for index, raw in enumerate(entries):
        found = _entry(
            raw=raw,
            where=f"{PUBLISHERS_KEY}[{index}]",
            taken={item.id for item in publishers},
        )
        if isinstance(found, str):
            errors.append(found)
        else:
            publishers.append(found)
    return PublisherConfig(publishers=publishers, errors=errors)
