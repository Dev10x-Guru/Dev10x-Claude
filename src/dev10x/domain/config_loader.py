"""ConfigLoader Protocol — shared interface for YAML config loading.

Defines the loading interface that config/loader.py implements
with msgpack caching. Standalone uv scripts in skills/permission/
may inline their own loading — this is an acceptable trade-off
since they run outside the dev10x package context.
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
