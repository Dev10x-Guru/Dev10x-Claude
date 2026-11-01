"""Canonical Dev10x plugin-identity regex fragment (GH-576).

A Dev10x plugin appears in cache paths as
``plugins/cache/<publisher>/<plugin-name>/<version>/``. The
``<plugin-name>`` segment historically had three divergent regex
fragments across the permission modules: ``clean`` matched a bare
``dev10x`` slug while ``doctor`` and ``update-paths`` did not. That
divergence meant a new slug alias had to be added in three places, and
``clean`` silently recognised paths the others rejected.

``PLUGIN_NAMES`` is the single canonical fragment. It is the most
permissive of the former three, so every consumer recognises every
slug the others did. Compile call-site patterns from this fragment
(combined with ``SEMVER_PATTERN`` from
``dev10x.domain.common.plugin_version`` where a version is also
needed) rather than re-declaring the alternation locally.
"""

from __future__ import annotations

# Core's own spellings: ``Dev10x``, ``dev10x`` and the legacy
# ``dev10x-claude`` slug. A rule under one of these belongs to core's
# cache directory, whatever it was called when the rule was written.
CORE_PLUGIN_NAMES = r"(?:Dev10x|dev10x(?:-claude)?)"

# Core plus every ``dev10x-<area>`` satellite (ADR-0034, GH-1564). A
# satellite rule lives in the satellite's own cache directory, so a
# consumer that rewrites the directory segment must test it against
# ``CORE_PLUGIN_NAMES`` first. Consumers that compile with
# ``re.IGNORECASE`` additionally match upper/mixed-case variants.
PLUGIN_NAMES = r"(?:Dev10x|dev10x(?:-[a-z]+)?)"

__all__ = ["CORE_PLUGIN_NAMES", "PLUGIN_NAMES"]
