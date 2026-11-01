"""The built supervisor page ships inside the package (GH-1692)."""

from __future__ import annotations

import re
from pathlib import Path

from dev10x.comm.overwatch.server import STATIC_DIR

ASSET_REFERENCE = re.compile(r'(?:src|href)="/(assets/[^"]+)"')


def test_index_is_built() -> None:
    assert (STATIC_DIR / "index.html").is_file()


def test_every_referenced_asset_exists() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    referenced = ASSET_REFERENCE.findall(html)

    assert (
        bool(referenced),
        [path for path in referenced if not (STATIC_DIR / path).is_file()],
    ) == (
        True,
        [],
    )


def test_package_data_ships_the_build() -> None:
    pyproject = (Path(__file__).resolve().parents[3] / "pyproject.toml").read_text()

    assert all(
        pattern in pyproject
        for pattern in ('"comm/overwatch/static/*.html"', '"comm/overwatch/static/assets/*"')
    )
