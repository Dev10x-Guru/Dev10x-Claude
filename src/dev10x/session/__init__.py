"""Session service package.

Re-exports the public surface of :mod:`dev10x.session.service`.
No logic lives here — per project convention, ``__init__.py`` is
for re-exports only.
"""

from __future__ import annotations

from dev10x.session.service import SessionService, SessionServiceError

__all__ = [
    "SessionService",
    "SessionServiceError",
]
