"""Abstract hook base with a Template Method ``run()`` (audit finding A11).

Hook feature functions share one lifecycle: resolve the input ``data``
(use what an orchestrator passed, else read stdin once) and then act on
it. :class:`AbstractHook` captures that invariant skeleton in ``run()``
and defers the variable step to the abstract ``handle()``.

Subclasses implement ``handle``; module-level functions stay as thin
shims (``Hook().run(data)``) so existing ``audit_hook(...)(fn)()`` entry
scripts and CLI command wrappers keep calling a plain function.
"""

from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod


def load_hook_stdin() -> dict:
    """Read a hook's JSON payload from stdin, tolerating empty/garbage input."""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return {}


class AbstractHook(ABC):
    """Template Method base: ``run`` owns the lifecycle, ``handle`` the work."""

    def run(self, data: dict | None = None) -> None:
        """Resolve input then delegate to ``handle``.

        ``data`` is what an in-process orchestrator already parsed; when
        ``None`` (standalone invocation) the payload is read from stdin.
        """
        self.handle(data=data if data is not None else load_hook_stdin())

    @abstractmethod
    def handle(self, *, data: dict) -> None:
        """Perform the hook's work against the resolved ``data``."""
