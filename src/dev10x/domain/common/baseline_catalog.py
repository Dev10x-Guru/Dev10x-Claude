"""Single chokepoint for reading ``baseline-permissions.yaml`` (GH-587).

Two consumers used to YAML-parse the baseline catalog independently —
``PolicyCatalog.load`` (projecting into ``list[Policy]``) and
``doctor.load_catalog`` (projecting into a ``Catalog`` dataclass). Two
parsers reading the same file is a schema-drift risk: a change to how the
baseline is read (encoding, tolerance, structural assumptions) had to be
mirrored in both places or they would silently diverge.

This module exposes one loader, :func:`load_baseline_dict`, that both
consumers route through. It only reads and YAML-parses the file into the
top-level mapping; each consumer keeps its own projection model — they
have different downstream consumers and must not be merged.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_baseline_dict(path: Path, *, strict: bool = False) -> dict:
    """Read and YAML-parse a baseline catalog file into its top-level mapping.

    ``strict=False`` (default) mirrors ``PolicyCatalog``'s tolerance: a
    missing file, a :class:`yaml.YAMLError`, or a non-mapping top-level
    value all return ``{}``.

    ``strict=True`` preserves ``doctor.load_catalog``'s raise-on-missing
    contract: a missing file raises :class:`FileNotFoundError`, a YAML
    error propagates, and a non-mapping top-level value raises
    :class:`ValueError`.
    """
    if not path.is_file():
        if strict:
            raise FileNotFoundError(f"Baseline catalog not found: {path}")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        if strict:
            raise
        return {}
    if not isinstance(data, dict):
        if strict:
            raise ValueError(f"Baseline catalog top-level value is not a mapping: {path}")
        return {}
    return data


__all__ = ["load_baseline_dict"]
