"""Rewrite versioned plugin-cache paths in settings files (GH-1432).

The default ``dev10x permission update-paths`` mode: every rule that
names ``plugins/cache/<publisher>/<plugin>/<X.Y.Z>/`` is moved onto the
latest installed version (and, when asked, a new publisher) so a plugin
upgrade does not strand the user's allow rules. Split out of
``update_paths.py`` by GH-1432.
"""

import json
import re
from pathlib import Path

from dev10x.domain.common.plugin_version import SEMVER_PATTERN
from dev10x.domain.plugin_identity import PLUGIN_NAMES
from dev10x.skills.permission.backup import backed_up_write

VERSION_PATTERN = re.compile(rf"(plugins/cache/)([^/]+)(/{PLUGIN_NAMES}/)({SEMVER_PATTERN})")


def _target_slug(*, plugin_slug: str, target_plugin_dir: str | None) -> str:
    """The ``/<plugin>/`` segment a rewritten path should carry (GH-1602)."""
    if not target_plugin_dir:
        return plugin_slug
    return f"/{target_plugin_dir}/"


def _rewrite_plugin_version_match(
    match: re.Match,
    *,
    target_publisher: str | None,
    target_version: str,
    target_plugin_dir: str | None = None,
) -> str:
    """Return the version/publisher/dir-rewritten text for a single match.

    Pure helper shared by the counting pass and the locked re-apply so
    both agree on the replacement without double-counting.
    """
    prefix = match.group(1)
    publisher = match.group(2)
    plugin_slug = match.group(3)
    old_ver = match.group(4)
    new_publisher = (
        target_publisher if target_publisher and publisher != target_publisher else publisher
    )
    new_slug = _target_slug(plugin_slug=plugin_slug, target_plugin_dir=target_plugin_dir)
    new_ver = target_version if old_ver != target_version else old_ver
    if new_publisher == publisher and new_slug == plugin_slug and new_ver == old_ver:
        return match.group(0)
    return prefix + new_publisher + new_slug + new_ver


def update_file(
    path: Path,
    target_version: str,
    *,
    target_publisher: str | None = None,
    target_plugin_dir: str | None = None,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """Move every pinned plugin-cache path onto the installed cache layout.

    ``target_plugin_dir`` is the plugin directory segment of the resolved
    cache (``dev10x``). GH-1501 renamed the plugin from ``Dev10x``, and a
    rule pinned under ``Dev10x/0.105.0`` used to get only its version
    bumped, pointing at a directory that does not exist (GH-1602).
    """
    content = path.read_text()
    old_versions: set[str] = set()
    old_publishers: set[str] = set()
    old_plugin_dirs: set[str] = set()
    count = 0

    def replacer(match: re.Match) -> str:
        nonlocal count
        prefix = match.group(1)
        publisher = match.group(2)
        plugin_slug = match.group(3)
        old_ver = match.group(4)

        new_publisher = publisher
        new_slug = _target_slug(plugin_slug=plugin_slug, target_plugin_dir=target_plugin_dir)
        new_ver = old_ver
        changed = False

        if target_publisher and publisher != target_publisher:
            old_publishers.add(publisher)
            new_publisher = target_publisher
            changed = True

        if new_slug != plugin_slug:
            old_plugin_dirs.add(plugin_slug.strip("/"))
            changed = True

        if old_ver != target_version:
            old_versions.add(old_ver)
            new_ver = target_version
            changed = True

        if changed:
            count += 1
            return prefix + new_publisher + new_slug + new_ver
        return match.group(0)

    new_content = VERSION_PATTERN.sub(replacer, content)

    if count > 0 and not dry_run:
        try:
            json.loads(new_content)
        except json.JSONDecodeError as e:
            return 0, [f"  SKIP (invalid JSON after replacement): {e}"]

        with backed_up_write(path=path) as live_data:
            live_text = json.dumps(live_data, indent=2) + "\n"
            rewritten = VERSION_PATTERN.sub(
                lambda m: _rewrite_plugin_version_match(
                    m,
                    target_publisher=target_publisher,
                    target_version=target_version,
                    target_plugin_dir=target_plugin_dir,
                ),
                live_text,
            )
            live_data.clear()
            live_data.update(json.loads(rewritten))

    messages = []
    for old_pub in sorted(old_publishers):
        messages.append(f"  publisher: {old_pub} -> {target_publisher}")
    for old_dir in sorted(old_plugin_dirs):
        messages.append(f"  plugin dir: {old_dir} -> {target_plugin_dir}")
    for old_ver in sorted(old_versions):
        messages.append(f"  {old_ver} -> {target_version} ({count} replacements)")
    return count, messages
