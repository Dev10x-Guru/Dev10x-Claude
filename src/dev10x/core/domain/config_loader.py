"""ConfigLoader Protocol — shared interface for YAML config loading.

This is a **Separated Interface** (Fowler PoEAA): the interface lives
in the ``domain/`` core while ``config/loader.py`` provides the
concrete implementation with msgpack caching — the same pattern as
``dev10x.domain.audit_writer.AuditWriter``. Standalone uv scripts in
skills/permission/ may inline their own loading — this is an
acceptable trade-off since they run outside the dev10x package
context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from dev10x.domain.documents.config_document import Config


@runtime_checkable
class ConfigLoader(Protocol):
    def __call__(
        self,
        yaml_path: Path,
        *,
        ttl_seconds: int = ...,
    ) -> Config: ...
