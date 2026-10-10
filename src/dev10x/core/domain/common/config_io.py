"""Shared read-only config/catalog deserialization (ADR-0015).

``load_yaml`` and ``load_json`` read and parse a config/catalog file
into its top-level mapping. They perform **read + parse only** — there
is no write counterpart; write-back stays in ``file_locks`` and the
Document layer (ADR-0007 D3, clarified by ADR-0015).

Tolerant mode (``strict=False``, the default) mirrors the shipped
``baseline_catalog.load_baseline_dict`` precedent: a missing file, a
parse error, or a non-mapping top-level value all return ``{}``. Strict
mode raises a single project error type, :class:`ConfigIOError`, so
callers that require the file fail uniformly regardless of the
underlying parser.

Scope: config/catalog *files* only — not subprocess stdout
(``json.loads(result.stdout)`` is a different category) and not inline
markdown frontmatter.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import yaml


class ConfigIOError(Exception):
    """Raised by the strict-mode loaders on any read or parse failure.

    Covers a missing file, malformed content, and a non-mapping
    top-level value — the underlying cause is chained via ``from``.
    """


def load_yaml(path: Path, *, strict: bool = False) -> dict:
    """Read and YAML-parse ``path`` into its top-level mapping."""
    return _load(path, parse=yaml.safe_load, parse_error=yaml.YAMLError, strict=strict)


def load_json(path: Path, *, strict: bool = False) -> dict:
    """Read and JSON-parse ``path`` into its top-level mapping."""
    return _load(path, parse=json.loads, parse_error=json.JSONDecodeError, strict=strict)


def _load(
    path: Path,
    *,
    parse: Callable[[str], object],
    parse_error: type[Exception],
    strict: bool,
) -> dict:
    if not path.is_file():
        if strict:
            raise ConfigIOError(f"Config file not found: {path}")
        return {}
    try:
        data = parse(path.read_text(encoding="utf-8"))
    except (parse_error, OSError) as exc:
        if strict:
            raise ConfigIOError(f"Failed to parse config file: {path}") from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise ConfigIOError(f"Config file top-level value is not a mapping: {path}")
        return {}
    return data


__all__ = ["ConfigIOError", "load_json", "load_yaml"]
