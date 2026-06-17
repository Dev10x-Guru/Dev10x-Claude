"""Single source of truth for the skill-audit transcript grammar (GH-588).

The normalized audit transcript (produced by ``extract_session.py``) is
parsed by two places that each used to define their own copy of these
regexes:

- ``dev10x.audit.permissions_model`` (Phase 4 permission friction)
- ``dev10x.skills.audit.analyze_actions`` (Phase 1 action inventory)

The copies drifted — the actions parser captured a trailing group on
``TURN_RE`` that the permissions parser discarded — so the same transcript
could be read two subtly different ways. This module owns the grammar.
``permissions_model`` imports it directly. ``analyze_actions`` is a PEP 723
standalone uv-script that keeps an inlined mirror (it must not import
``dev10x`` at module scope); ``tests/audit/test_transcript_grammar.py``
asserts the mirror stays identical to this source of truth.

``TURN_RE`` exposes four groups: turn number, timestamp, role, and the
trailing remainder of the heading line (used to detect ``[CORRECTION]``
markers). Callers that need only the first three groups ignore the fourth.
"""

from __future__ import annotations

import re

TURN_RE = re.compile(
    r"^## Turn (\d+) \[([^\]]+)\] (USER|ASSISTANT)(.*)",
    re.MULTILINE,
)

TOOL_RE = re.compile(r"^\*\*Tool: `([^`]+)`\*\*", re.MULTILINE)

TOOL_INPUT_BLOCK_RE = re.compile(
    r"^\*\*Tool: `([^`]+)`\*\*\n```\n(.*?)```",
    re.MULTILINE | re.DOTALL,
)
