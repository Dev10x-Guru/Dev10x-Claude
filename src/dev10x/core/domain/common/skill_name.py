"""SkillName value object — `<namespace>:<slug>` skill identifier.

Eliminates duplicate parsing scattered across `hooks/skill.py`
(safe-path naming) and `skills/audit/cli_friction.py`
(directory lookup). Audit finding C4 — 2026-05-18.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillName:
    namespace: str | None
    slug: str

    def __str__(self) -> str:
        if self.namespace:
            return f"{self.namespace}:{self.slug}"
        return self.slug

    @property
    def short_name(self) -> str:
        return self.slug

    @property
    def safe_path_name(self) -> str:
        full = str(self)
        # Replace `:` with `-`, then strip anything outside [A-Za-z0-9._-].
        return re.sub(r"[^a-zA-Z0-9._-]", "", full.replace(":", "-"))

    @classmethod
    def parse(cls, value: str) -> SkillName:
        if not isinstance(value, str) or not value:
            raise ValueError(f"Invalid skill name: {value!r}")
        if ":" in value:
            namespace, slug = value.split(":", 1)
            if not namespace or not slug:
                raise ValueError(f"Invalid namespaced skill name: {value!r}")
            return cls(namespace=namespace, slug=slug)
        return cls(namespace=None, slug=value)

    @classmethod
    def try_parse(cls, value: str) -> SkillName | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None
