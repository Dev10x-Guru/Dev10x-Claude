from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from dev10x.domain.file_locks import atomic_write_text

ANSWER_WAIT_DEFAULT = 120
ANSWER_WAIT_MAX = 540


def clamp_wait(*, seconds: int) -> int:
    return min(ANSWER_WAIT_MAX, max(0, seconds))


@dataclass(frozen=True)
class PageSettings:
    answer_wait_seconds: int = ANSWER_WAIT_DEFAULT


class SettingsStore:
    def __init__(self, *, path: Path) -> None:
        self._path = path

    def load(self) -> PageSettings:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            wait = int(data["answer_wait_seconds"])
        except (OSError, ValueError, TypeError, KeyError):
            return PageSettings()
        return PageSettings(answer_wait_seconds=clamp_wait(seconds=wait))

    def save(self, *, settings: PageSettings) -> PageSettings:
        stored = PageSettings(answer_wait_seconds=clamp_wait(seconds=settings.answer_wait_seconds))
        atomic_write_text(self._path, json.dumps(asdict(stored)))
        return stored
