"""Shapes that let a granted rule run other programs (GH-1723).

``grant.py`` refuses whole-executable grants for tools that run arbitrary
code, but two gaps survived GH-1687:

- an interpreter not on its denylist (``lua``, ``tclsh``, a versioned
  ``python3.12``) passes the depth check one word deep, so
  ``Bash(lua script:*)`` runs any file named ``script``;
- an allowlisted tool can still execute another program through a flag:
  ``rg --pre=<cmd>``, ``sort --compress-program=<cmd>``,
  ``make --eval='$(shell …)'``.

Kept apart from ``grant.py`` so the tables can grow without touching the
triage flow.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Interpreters run whatever script or expression they are handed, so a
#: rule for one is an arbitrary-code grant at any depth.
INTERPRETERS = frozenset(
    {
        "ash",
        "bun",
        "busybox",
        "clisp",
        "csh",
        "deno",
        "elixir",
        "erl",
        "escript",
        "expect",
        "gawk",
        "groovy",
        "guile",
        "iex",
        "ipython",
        "irb",
        "java",
        "jruby",
        "jshell",
        "julia",
        "kotlin",
        "ksh",
        "lua",
        "luajit",
        "mawk",
        "mksh",
        "nawk",
        "node",
        "osascript",
        "perl",
        "php",
        "powershell",
        "pwsh",
        "pypy",
        "python",
        "r",
        "racket",
        "rscript",
        "ruby",
        "sbcl",
        "scala",
        "swift",
        "tclsh",
        "tcsh",
        "ts-node",
        "tsx",
        "wish",
    }
)

#: Flags through which an otherwise read-only tool executes a program.
EXEC_FLAGS: dict[str, tuple[str, ...]] = {
    "make": ("--eval", "-E", "-f", "--file", "--makefile"),
    "rg": ("--pre", "--pre-glob"),
    "sort": ("--compress-program",),
}

_VERSION_SUFFIX_RE = re.compile(r"[\d.]+$")


def _base_name(*, executable: str) -> str:
    name = Path(executable).name.lower()
    stripped = _VERSION_SUFFIX_RE.sub("", name)
    return stripped or name


def is_interpreter(*, executable: str) -> bool:
    """True for ``lua``, ``/usr/bin/python3.12``, ``perl5`` and the like."""
    return _base_name(executable=executable) in INTERPRETERS


def exec_flag(*, words: list[str]) -> str | None:
    """The exec-capable flag ``words`` passes to its tool, if any.

    Matches the bare flag and its ``--flag=value`` form. A one-letter
    flag also matches anywhere in a short-option cluster (``-kf``,
    ``-Efoo``); over-matching there only refuses, the safe direction.
    """
    flags = EXEC_FLAGS.get(Path(words[0]).name, ())
    for word in words[1:]:
        in_cluster = word.startswith("-") and not word.startswith("--")
        for flag in flags:
            if word == flag or word.startswith(f"{flag}="):
                return flag
            if not flag.startswith("--") and in_cluster and flag[1] in word[1:]:
                return flag
    return None


__all__ = ["EXEC_FLAGS", "INTERPRETERS", "exec_flag", "is_interpreter"]
