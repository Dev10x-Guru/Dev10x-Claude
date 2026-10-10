"""Backwards-compatible re-export.

Canonical primitives live in :mod:`dev10x.domain.file_locks`. This
shim preserves the existing import path for permission-skill call
sites.
"""

from __future__ import annotations

from dev10x.domain.file_locks import locked_json_update

__all__ = ["locked_json_update"]
