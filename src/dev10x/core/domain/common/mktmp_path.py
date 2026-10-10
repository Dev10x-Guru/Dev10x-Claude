"""MktmpPath value object — ``/tmp/Dev10x/<session>/<file>.<entropy>`` paths.

The high-entropy ephemeral path shape produced by ``mktmp`` was matched by
four independent regexes that all re-embedded the same
``/tmp/Dev10x/<session>/<file>.<random{6,}>`` structure with slightly
different anchoring and extension lists (audit finding GH-523-B —
2026-06-10).

Two distinct uses share the structure:

* **Detection** — is this an ephemeral temp path? (the Write-overwrite
  gate; the worktree-merge noise filter). Use :meth:`is_mktmp_path`.
* **Generalisation** — collapse a concrete temp path to a glob in a
  permission rule. Callers keep their own replacement (``\\1*`` vs
  ``\\1**``) but share :data:`MKTMP_GENERALIZE_PATTERN`, whose first
  group captures the session directory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MKTMP_PATH_PATTERN = r"/tmp/Dev10x/[^/]+/[^/]+\.[A-Za-z0-9]{6,}"
# Generalisation form: capture the session dir (group 1), match the
# random filename plus a known doc extension so callers can glob it.
MKTMP_GENERALIZE_PATTERN = r"(/tmp/Dev10x/[^/]+/)[^/)]+\.[A-Za-z0-9]{6,}\.(?:txt|md|json)"

_SEARCH_RE = re.compile(MKTMP_PATH_PATTERN)
_WITH_EXTENSION_RE = re.compile(rf"{MKTMP_PATH_PATTERN}\.\w+$")


@dataclass(frozen=True)
class MktmpPath:
    @classmethod
    def is_mktmp_path(cls, value: str, *, require_extension: bool = False) -> bool:
        """True when ``value`` contains an ephemeral mktmp path.

        ``require_extension`` anchors the match to the end of the string
        and requires a trailing ``.<ext>`` — the shape that trips the
        Write-overwrite gate.
        """
        if require_extension:
            return bool(_WITH_EXTENSION_RE.search(value))
        return bool(_SEARCH_RE.search(value))
