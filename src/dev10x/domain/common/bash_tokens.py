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
import shlex

# A single leading environment-variable assignment token, e.g. ``FOO=bar``.
# Matched against one already-split argv token — anchored at both ends.
# Uppercase-only by design, and pinned by test_bash_tokens.py: callers use
# it to recognise the conventional exported-variable spelling.
ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")

# The same token shape, but case-insensitive (GH-1084). Deliberately a
# SEPARATE name rather than a widened ENV_VAR_RE, because the two have
# genuinely different jobs and GH-583/N24 is this module's cautionary tale
# about one name carrying two semantics:
#
#   ENV_VAR_RE           — "does this look like an env assignment?"
#   ANY_CASE_ENV_VAR_RE  — "is this token something OTHER than the program
#                           being run?", used to skip past prefixes while
#                           resolving a command's executable.
#
# For the second job, under-matching is the dangerous direction: POSIX
# permits lowercase names, so `foo=bar ./guarded.sh` would otherwise
# resolve its executable to `foo=bar` and let the guarded script through.
ANY_CASE_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


def split_tokens(*, command: str) -> list[str]:
    """Shell-split ``command``, falling back to whitespace on bad quoting.

    ``shlex.split`` raises on an unbalanced quote. Treating that as
    "cannot tokenize, therefore skip the check" would hand back an
    evasion, so callers get a best-effort token list instead.
    """
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


# ``git -C <dir>`` at the start of a command — a boolean prefix probe.
# Used by the permission-audit model to classify a poisoned prefix.
GIT_C_PREFIX_RE = re.compile(r"^git\s+-C\s+")

# ``git -C <dir>`` anywhere in a command, capturing the directory argument
# (with optional single/double quotes). Used to rewrite the command back to
# a bare ``git`` invocation. Distinct semantics from GIT_C_PREFIX_RE: this
# one searches and captures rather than anchoring and probing.
GIT_C_DIR_RE = re.compile(r'\bgit\s+-C\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)')


def substitution_bodies(command: str, *, include_backticks: bool) -> list[str]:
    """Bodies of the command substitutions in ``command``.

    Depth-aware, so a nested substitution does not truncate its parent:
    ``$(python3 -c "$(echo x)")`` yields the whole ``python3 …`` body, not
    just the inner ``echo x``. A regex cannot do this — ``\\$\\(([^()]*)\\)``
    stops at the first inner paren and silently hands back only the
    innermost body, which is a detection gap for any caller checking what
    a substitution actually runs.

    Only the outermost bodies are returned; a caller that also wants the
    nested ones re-scans each result (see
    ``execution_safety._command_units``).

    ``include_backticks`` selects whether legacy `` `…` `` spans count.
    The interpreter guard wants them; DX001's subshell allow-list is
    specified against ``$( … )`` only and passes ``False`` so its
    behaviour is unchanged.

    An unbalanced opener is skipped rather than treated as extending to
    end-of-string — a truncated tail is not a command anyone ran.
    """
    bodies: list[str] = []
    index = 0
    while index < len(command):
        if command.startswith("$(", index):
            depth = 1
            cursor = index + 2
            while cursor < len(command) and depth:
                if command[cursor] == "(":
                    depth += 1
                elif command[cursor] == ")":
                    depth -= 1
                cursor += 1
            if depth:
                index += 1
                continue
            bodies.append(command[index + 2 : cursor - 1])
            index = cursor
        elif include_backticks and command[index] == "`":
            close = command.find("`", index + 1)
            if close == -1:
                index += 1
                continue
            bodies.append(command[index + 1 : close])
            index = close + 1
        else:
            index += 1
    return bodies
