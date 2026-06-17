"""Tests for the CLI `_require_context` helper (GH-584, audit N18).

The CLI counterpart to the MCP adapter's service call: it unwraps
`load_permission_context` or exits 1 when config resolution fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.commands import permission as cmd
from dev10x.domain.common.result import err, ok
from dev10x.permission.service import PermissionContext


def test_returns_context_value(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = PermissionContext(config_path=Path("/cfg.yaml"), config={"roots": []}, settings_files=[])
    monkeypatch.setattr(cmd, "load_permission_context", lambda *, include_user=None: ok(ctx))
    assert cmd._require_context() is ctx


def test_exits_when_config_resolution_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cmd, "load_permission_context", lambda *, include_user=None: err("no config")
    )
    with pytest.raises(SystemExit) as excinfo:
        cmd._require_context()
    assert excinfo.value.code == 1
