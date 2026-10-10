"""Quote-aware tokenization for bash command validators.

Strips inert quoted spans so threat-pattern regexes (subshells, brace
expansion, etc.) only see the genuinely active remainder.

What is stripped:
  - Single-quoted spans ``'...'`` are removed entirely. Every character
    inside single quotes is literal — even backslashes — so a ``$(``
    appearing there is inert text, not a subshell.
  - ANSI-C strings ``$'...'`` are removed entirely. They expand to a
    fixed byte sequence; no command substitution or variable expansion
    is possible inside.
  - Backslash escapes outside quotes drop both characters so an escaped
    ``\\$`` is not mistaken for an expansion.

What is preserved:
  - Double-quoted spans ``"..."`` keep their full contents. Inside
    double quotes ``$`` and backtick remain active, so any substitution
    or variable that lives there must still be visible to threat
    detectors.
  - All unquoted characters.

The output is a pattern-matching surface, not an editable command —
column offsets into the result are not meaningful.
"""

from __future__ import annotations


def quote_strip(command: str) -> str:
    """Return ``command`` with inert quoted spans removed.

    See module docstring for the exact semantics.
    """
    result: list[str] = []
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "$" and i + 1 < n and command[i + 1] == "'":
            i = _scan_ansi_c(command=command, start=i + 2)
            continue
        if ch == "'":
            j = command.find("'", i + 1)
            if j == -1:
                return "".join(result)
            i = j + 1
            continue
        if ch == '"':
            j = _scan_double_quoted(command=command, start=i + 1)
            result.append(command[i:j])
            i = j
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _scan_ansi_c(*, command: str, start: int) -> int:
    """Return the index just past the closing ``'`` of an ANSI-C string."""
    j = start
    n = len(command)
    while j < n:
        if command[j] == "\\" and j + 1 < n:
            j += 2
            continue
        if command[j] == "'":
            return j + 1
        j += 1
    return n


def _scan_double_quoted(*, command: str, start: int) -> int:
    """Return the index just past the closing ``"`` of a double-quoted span."""
    j = start
    n = len(command)
    while j < n:
        if command[j] == "\\" and j + 1 < n:
            j += 2
            continue
        if command[j] == '"':
            return j + 1
        j += 1
    return n
