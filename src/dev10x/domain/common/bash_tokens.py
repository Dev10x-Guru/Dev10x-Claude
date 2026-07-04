"""Shared regexes for recognising bash command tokens.

Several validators and the permission-audit model each need to
recognise the same shell-token shapes (leading env-var assignments,
``git -C <dir>`` prefixes). Defining these patterns once here keeps
their semantics unambiguous — previously ``ENV_VAR_RE`` was duplicated
across three validators and two ``GIT_C_RE`` regexes with *different*
semantics shared a single name in separate modules (GH-583, N24).
"""

from __future__ import annotations

import re

# A single leading environment-variable assignment token, e.g. ``FOO=bar``.
# Matched against one already-split argv token — anchored at both ends.
ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")

# ``git -C <dir>`` at the start of a command — a boolean prefix probe.
# Used by the permission-audit model to classify a poisoned prefix.
GIT_C_PREFIX_RE = re.compile(r"^git\s+-C\s+")

# ``git -C <dir>`` anywhere in a command, capturing the directory argument
# (with optional single/double quotes). Used to rewrite the command back to
# a bare ``git`` invocation. Distinct semantics from GIT_C_PREFIX_RE: this
# one searches and captures rather than anchoring and probing.
GIT_C_DIR_RE = re.compile(r'\bgit\s+-C\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)')
