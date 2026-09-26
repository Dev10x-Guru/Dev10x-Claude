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

    @classmethod
    def try_parse(cls, value: str) -> RepositoryRef | None:
        try:
            return cls.parse(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def basename_or(cls, value: str, *, fallback: str | None = None) -> str:
        """Return the bare repo name from an ``owner/name`` string.

        Parses via :meth:`try_parse` first, so a malformed ``value`` does
        not silently produce a wrong or empty basename (GH-1451). Falls
        back to ``fallback`` — or the last ``/``-delimited segment when
        ``fallback`` is omitted — only when the string does not parse.
        """
        ref = cls.try_parse(value)
        if ref is not None:
            return ref.name
        if fallback is not None:
            return fallback
        return value.rsplit("/", maxsplit=1)[-1]
