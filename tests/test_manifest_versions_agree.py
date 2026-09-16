"""Keep the two plugin manifests on the same version (GH-1310).

The Claude Code Plugins panel renders an installed plugin from its
**marketplace entry**, not from ``plugin.json``. That entry carried no
``version`` key at all, so the panel had nothing to show — while
``plugin.json`` had been tracking the real version all along. The proof
of which file the panel reads was a stale ``description`` rendered
verbatim from ``marketplace.json`` months after ``plugin.json``'s copy
had moved on.

Neither half could self-heal: ``.bumpversion.toml`` listed only
``plugin.json``, so a release never touched ``marketplace.json``. The
fix adds the key and the bumpversion entry; this guard is what stops the
pair drifting apart again, because nothing about editing one manifest
hints that a second one exists.

The duplicated ``description`` is deliberately gone from
``marketplace.json`` rather than kept in sync by a second bumpversion
entry — one source of truth beats two a tool has to reconcile.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parents[1]

_PLUGIN_MANIFEST = _REPO_ROOT / ".claude-plugin" / "plugin.json"
_MARKETPLACE_MANIFEST = _REPO_ROOT / ".claude-plugin" / "marketplace.json"
_BUMPVERSION = _REPO_ROOT / ".bumpversion.toml"
_RELEASE_SCRIPT = _REPO_ROOT / "bin" / "release.sh"


def _bumpversion_files() -> set[str]:
    return {
        entry["filename"]
        for entry in tomllib.loads(_BUMPVERSION.read_text())["tool"]["bumpversion"]["files"]
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _marketplace_entry(*, name: str) -> dict[str, Any]:
    plugins = _load_json(_MARKETPLACE_MANIFEST)["plugins"]
    matches = [plugin for plugin in plugins if plugin.get("name") == name]
    assert matches, f"marketplace.json has no plugins[] entry named {name!r}"
    return matches[0]


def test_the_marketplace_entry_declares_a_version() -> None:
    entry = _marketplace_entry(name=_load_json(_PLUGIN_MANIFEST)["name"])
    assert entry.get("version"), (
        "marketplace.json's plugins[] entry needs a 'version' — the Plugins "
        "panel reads it from here, not from plugin.json"
    )


def test_both_manifests_report_the_same_version() -> None:
    plugin = _load_json(_PLUGIN_MANIFEST)
    entry = _marketplace_entry(name=plugin["name"])
    assert entry["version"] == plugin["version"], (
        f"marketplace.json says {entry['version']!r} but plugin.json says "
        f"{plugin['version']!r} — a release must move both. Check that "
        ".bumpversion.toml still lists marketplace.json."
    )


def test_bumpversion_moves_the_marketplace_manifest() -> None:
    """The guard above only bites after a release; this one bites before it.

    Without the bumpversion entry the two manifests agree exactly once —
    on the commit that hand-edited them — and diverge on the next bump.
    """
    configured = _bumpversion_files()
    assert ".claude-plugin/marketplace.json" in configured, (
        "'.claude-plugin/marketplace.json' is missing from .bumpversion.toml "
        "[[tool.bumpversion.files]] — its version would freeze at the next bump"
    )


def test_the_release_script_stages_every_versioned_file() -> None:
    """Adding a bumpversion entry is only half the wiring.

    ``bin/release.sh`` rewrites versions with ``--no-commit`` and then
    stages its own hardcoded ``VERSION_FILES`` list. A file bumpversion
    rewrites but the script never stages is left dirty, and the *next*
    ``bump-my-version`` call in the same run aborts on an unclean tree —
    stranding the release between the patch bump and the finalize.
    GH-1310 added the marketplace entry and left this list untouched,
    which is exactly how the 0.100.1 release failed mid-flight.
    """
    version_files = _RELEASE_SCRIPT.read_text(encoding="utf-8")
    missing = sorted(name for name in _bumpversion_files() if name not in version_files)
    assert not missing, (
        f"{missing} appear in .bumpversion.toml but not in bin/release.sh's "
        "VERSION_FILES — the release would leave them unstaged and abort on "
        "the next bump"
    )


def test_the_description_is_not_duplicated_across_manifests() -> None:
    """Two descriptions is the drift that exposed GH-1310 in the first place."""
    entry = _marketplace_entry(name=_load_json(_PLUGIN_MANIFEST)["name"])
    assert "description" not in entry, (
        "marketplace.json's plugins[] entry should not carry its own "
        "'description' — plugin.json owns it, and the copy here went stale "
        "because no release step updated it"
    )


def _shipped_skill_count() -> int:
    return len(list((_REPO_ROOT / "skills").glob("*/SKILL.md")))


def test_the_description_counts_the_skills_actually_shipped() -> None:
    """The one claim in that string a release does not maintain (GH-1356).

    ``.bumpversion.toml`` rewrites the ``v{version} —`` prefix on every
    release, so the version half of the description looks after itself.
    The skill count sits in the same sentence with no such entry and no
    other step recomputing it, so it only moves when someone hand-edits
    it — and it had drifted to 69 against 91 shipped skills.

    That asymmetry is worse than uniform staleness: a correct version
    beside a wrong count invites trusting both. The GH-1310 field test
    did exactly that, certifying "the version reads v0.101.1 and the
    skill count reads 69, both current" against a number 22 out.

    The expected value is derived rather than pinned, so adding a skill
    fails here with the new number in the message and the fix is a
    one-character edit instead of a rediscovery.
    """
    description = _load_json(_PLUGIN_MANIFEST)["description"]
    match = re.search(r"(\d+) skills", description)
    assert match, (
        "plugin.json's description no longer states a skill count in the "
        "form '<N> skills' — if the wording changed deliberately, update "
        "this guard rather than deleting it"
    )

    expected = _shipped_skill_count()
    assert int(match.group(1)) == expected, (
        f"plugin.json's description says {match.group(1)} skills but "
        f"skills/*/SKILL.md counts {expected} — the Plugins panel renders "
        "this string verbatim, so the count a supervisor reads is wrong"
    )
