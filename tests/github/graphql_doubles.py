"""Shared doubles for tests of GraphQL-backed GitHub tools."""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.dev10x_paths import Dev10xConfigDir

from tests.fakers.process import completed

__all__ = ["completed", "write_merge_settings"]


def write_merge_settings(*, text: str) -> Path:
    path = Dev10xConfigDir.settings_pr_merge_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
