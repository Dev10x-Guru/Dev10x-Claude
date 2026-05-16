from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepositoryRef:
    owner: str
    name: str

    def __str__(self) -> str:
        return f"{self.owner}/{self.name}"

    @classmethod
    def parse(cls, value: str) -> RepositoryRef:
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            msg = f"Invalid repository reference: {value!r}. Expected 'owner/name' format."
            raise ValueError(msg)
        return cls(owner=parts[0], name=parts[1])
