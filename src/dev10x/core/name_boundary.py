"""Where a command, role or skill name starts and ends inside free text.

A name such as ``gh``, ``rg`` or ``aws-vault`` is matched as a whole
word, where a hyphen counts as part of the word: ``gh`` must not match
inside ``ugh`` or ``gh-pages``, and ``rg`` must not match inside
``merge``. Every regex matcher that looks for a name in prose or a
command line shares these two lookarounds so they cannot drift apart.
DX020 compares whole name tokens instead and reaches for
``name_pattern`` only for an alias that is not a single token.

Imports nothing beyond the standard library and lives outside
``dev10x.domain``, whose package init needs yaml, so the
dependency-free bin/ scanners can import it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

NAME_START = r"(?<![\w-])"
NAME_END = r"(?![\w-])"


def name_pattern(*, names: Iterable[str], flags: int = 0) -> re.Pattern[str]:
    """A pattern matching any of ``names`` as a whole, hyphen-aware word."""
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(rf"{NAME_START}(?:{alternatives}){NAME_END}", flags)
