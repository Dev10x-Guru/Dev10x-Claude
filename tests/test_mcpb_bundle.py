"""Keep the MCPB bundle manifest wired into the release (GH-1675).

``manifest.json`` is the fourth file a release must version, and the one
whose drift nothing else would catch until ``mcpb-release.yml`` refused
a tag. These guards fail on the PR instead.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).parents[1]

_MCPB_MANIFEST = _REPO_ROOT / "manifest.json"
_MCPB_IGNORE = _REPO_ROOT / ".mcpbignore"
_PLUGIN_MANIFEST = _REPO_ROOT / ".claude-plugin" / "plugin.json"
_BUMPVERSION = _REPO_ROOT / ".bumpversion.toml"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "mcpb-release.yml"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def manifest() -> dict[str, Any]:
    return _load_json(_MCPB_MANIFEST)


@pytest.fixture
def ignored_patterns() -> set[str]:
    lines = _MCPB_IGNORE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_the_bundle_reports_the_plugin_version(manifest: dict[str, Any]) -> None:
    plugin_version = _load_json(_PLUGIN_MANIFEST)["version"]
    assert manifest["version"] == plugin_version, (
        f"manifest.json says {manifest['version']!r} but plugin.json says "
        f"{plugin_version!r} — mcpb-release.yml rejects a tag whose bundle "
        "version disagrees"
    )


def test_bumpversion_moves_the_bundle_manifest() -> None:
    configured = {
        entry["filename"]
        for entry in tomllib.loads(_BUMPVERSION.read_text())["tool"]["bumpversion"]["files"]
    }
    assert "manifest.json" in configured, (
        "'manifest.json' is missing from .bumpversion.toml "
        "[[tool.bumpversion.files]] — the bundle version would freeze at the "
        "next bump and the release workflow would refuse the tag"
    )


def test_the_bundle_launches_the_cli_server(manifest: dict[str, Any]) -> None:
    entry_point = _REPO_ROOT / manifest["server"]["entry_point"]
    assert entry_point.is_file(), f"{entry_point} does not exist"
    assert (
        f"${{__dirname}}/{manifest['server']['entry_point']}"
        in (manifest["server"]["mcp_config"]["args"])
    ), "mcp_config.args must launch the declared entry_point from ${__dirname}"


@pytest.mark.parametrize(
    "required",
    [
        "src/dev10x/mcp/server_cli.py",
        "servers/cli_server.py",
        "skills/gh-pr-create",
        ".claude-plugin/plugin.json",
    ],
)
def test_the_bundle_keeps_what_the_cli_server_reads(
    ignored_patterns: set[str],
    required: str,
) -> None:
    top_level = required.split("/")[0] + "/"
    assert top_level not in ignored_patterns, (
        f".mcpbignore drops {top_level} — the cli server resolves its plugin "
        f"root from its own path and needs {required} in the bundle"
    )
    assert (_REPO_ROOT / required).exists()


def test_the_release_workflow_pins_the_mcpb_cli() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    assert 'MCPB_VERSION: "' in workflow, (
        "mcpb-release.yml must pin the mcpb CLI — an unpinned npx resolves "
        "whatever is newest at release time"
    )
