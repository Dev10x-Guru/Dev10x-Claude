from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class Run:
    exit_code: int
    stdout: str
    stderr: str


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "claude-bus"


@pytest.fixture
def run_main(
    capsys: pytest.CaptureFixture[str],
) -> Callable[[Callable[..., int], list[str]], Run]:
    def run(main: Callable[..., int], argv: list[str]) -> Run:
        exit_code = main(argv=argv)
        captured = capsys.readouterr()
        return Run(exit_code=exit_code, stdout=captured.out, stderr=captured.err)

    return run
