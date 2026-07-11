from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import msgpack
import yaml

from dev10x.domain.config_loader import ConfigLoader
from dev10x.domain.documents.config_document import Config
from dev10x.domain.file_locks import atomic_write_bytes
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.rules.validation_rule import Compensation, MatchingRule

DEFAULT_TTL_SECONDS = 1800


def load_config(
    yaml_path: Path,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Config:
    cache_path = yaml_path.with_suffix(".msgpack")

    cached = _read_cache(
        cache_path=cache_path,
        yaml_path=yaml_path,
        ttl_seconds=ttl_seconds,
    )
    if cached is not None:
        return cached

    config = _parse_yaml(yaml_path=yaml_path)
    _write_cache(cache_path=cache_path, config=config)
    return config


assert isinstance(load_config, ConfigLoader)


def _read_cache(
    *,
    cache_path: Path,
    yaml_path: Path,
    ttl_seconds: int,
) -> Config | None:
    if not cache_path.exists():
        return None

    try:
        cache_mtime = cache_path.stat().st_mtime
        yaml_mtime = yaml_path.stat().st_mtime

        if yaml_mtime > cache_mtime:
            return None

        age = time.time() - cache_mtime
        if age > ttl_seconds:
            return None

        raw = msgpack.unpackb(cache_path.read_bytes(), raw=False)
        return _dict_to_config(raw=raw)
    except (msgpack.UnpackException, KeyError, TypeError, OSError):
        return None


def _write_cache(*, cache_path: Path, config: Config) -> None:
    try:
        data = asdict(config)
        atomic_write_bytes(cache_path, msgpack.packb(data, use_bin_type=True))
    except (msgpack.PackException, OSError):
        pass


def _parse_yaml(*, yaml_path: Path) -> Config:
    data: dict[str, Any] = yaml.safe_load(yaml_path.read_text()) or {}
    cfg_data = data.get("config", {})

    rules = [MatchingRule.from_yaml_entry(entry=entry) for entry in data.get("rules", [])]

    return Config(
        friction_level=FrictionLevel.from_yaml(cfg_data.get("friction_level")),
        plugin_repo=cfg_data.get("plugin_repo", ""),
        rules=rules,
    )


def _dict_to_config(*, raw: dict[str, Any]) -> Config:
    rules = [
        MatchingRule(
            name=r["name"],
            patterns=r["patterns"],
            matcher=r.get("matcher", "Bash"),
            except_=r.get("except_", []),
            compensations=[Compensation(**c) for c in r.get("compensations", [])],
            hook_block=r.get("hook_block", True),
            reason=r.get("reason", ""),
            message=r.get("message", ""),
            related=r.get("related", []),
            file_pattern=r.get("file_pattern", ""),
            file_names=r.get("file_names", []),
            file_prefixes=r.get("file_prefixes", []),
            file_substrings=r.get("file_substrings", []),
            content_pattern=r.get("content_pattern", ""),
        )
        for r in raw.get("rules", [])
    ]
    return Config(
        friction_level=FrictionLevel.from_yaml(raw.get("friction_level")),
        plugin_repo=raw.get("plugin_repo", ""),
        rules=rules,
    )
