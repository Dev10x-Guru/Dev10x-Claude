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
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import lru_cache
from itertools import permutations

# Both lexing entry points are pure, and one hook process asks several
# validators (and several checks inside DX003) about the same strings.
_LEX_CACHE_SIZE = 256

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


@dataclass(frozen=True)
class _Wrapper:
    """A process wrapper that runs the rest of argv as a command.

    ``value_options`` consume the next token; ``positionals`` counts the
    operands taken before the wrapped command (``timeout``'s duration).
    """

    value_options: frozenset[str] = frozenset()
    positionals: int = 0
    # Options whose value is itself a command line, split into words in
    # place: `env -S 'python -c x'` runs `python -c x` (GH-1798).
    split_options: frozenset[str] = frozenset()


_COMMAND_WRAPPERS: dict[str, _Wrapper] = {
    "env": _Wrapper(
        value_options=frozenset({"-u", "--unset", "-C", "--chdir"}),
        split_options=frozenset({"-S", "--split-string"}),
    ),
    "timeout": _Wrapper(
        value_options=frozenset({"-s", "--signal", "-k", "--kill-after"}), positionals=1
    ),
    "nice": _Wrapper(value_options=frozenset({"-n", "--adjustment"})),
    "stdbuf": _Wrapper(value_options=frozenset({"-i", "-o", "-e"})),
    "nohup": _Wrapper(),
    "exec": _Wrapper(value_options=frozenset({"-a"})),
    "command": _Wrapper(),
    "time": _Wrapper(value_options=frozenset({"-f", "--format", "-o", "--output"})),
    # Runners that execute the command named in their arguments (GH-1774).
    "sudo": _Wrapper(
        value_options=frozenset(
            {
                "-u",
                "--user",
                "-g",
                "--group",
                "-h",
                "--host",
                "-p",
                "--prompt",
                "-C",
                "--close-from",
                "-D",
                "--chdir",
                "-R",
                "--chroot",
                "-T",
                "--command-timeout",
                "-U",
                "--other-user",
                "-r",
                "--role",
                "-t",
                "--type",
            }
        )
    ),
    "doas": _Wrapper(value_options=frozenset({"-u", "-C"})),
    # More runners that execute the rest of argv (GH-1798). chroot's
    # positional is the new root; its own options use the `=` form.
    "setsid": _Wrapper(),
    "pkexec": _Wrapper(value_options=frozenset({"--user"})),
    "chroot": _Wrapper(value_options=frozenset({"--userspec", "--groups"}), positionals=1),
    "nsenter": _Wrapper(
        value_options=frozenset({"-t", "--target", "-S", "--setuid", "-G", "--setgid"})
    ),
    # Tracers, schedulers and terminal helpers that exec the rest of argv
    # (GH-1998). taskset's and chrt's positional is the mask or priority.
    "strace": _Wrapper(
        value_options=frozenset(
            {"-o", "-e", "-p", "-s", "-u", "-E", "-a", "-b", "-I", "-O", "-S", "-P", "-X", "-U"}
            | {"--output", "--trace", "--signal", "--attach", "--string-limit", "--user"}
            | {"--env", "--columns", "--detach-on", "--interruptible", "--overhead"}
            | {"--summary-sort-by", "--trace-path", "--const-print-style", "--summary-columns"}
        )
    ),
    "ltrace": _Wrapper(
        value_options=frozenset(
            {"-o", "-e", "-p", "-s", "-u", "-a", "-n", "-l", "-L", "-x", "-A", "-D", "-F"}
            | {"--output", "--align", "--indent", "--library", "--config"}
        )
    ),
    "valgrind": _Wrapper(),
    "ionice": _Wrapper(value_options=frozenset({"-c", "--class", "-n", "--classdata"})),
    "taskset": _Wrapper(positionals=1),
    "chrt": _Wrapper(
        value_options=frozenset(
            {"-T", "-P", "-D", "--sched-runtime", "--sched-period", "--sched-deadline"}
        ),
        positionals=1,
    ),
    "unbuffer": _Wrapper(),
    # rlwrap's -a, -i, -m, -n, -o and -p take only an attached optional
    # value, so they are flags here.
    "rlwrap": _Wrapper(
        value_options=frozenset(
            {"-b", "-C", "-D", "-e", "-f", "-g", "-H", "-l", "-O", "-P", "-q"}
            | {"-s", "-S", "-t", "-w", "-z"}
        )
    ),
    "systemd-run": _Wrapper(
        value_options=frozenset(
            {"-u", "--unit", "-p", "--property", "-E", "--setenv", "--uid", "--gid"}
            | {"--nice", "--slice", "--description", "-M", "--machine", "-H", "--host"}
            | {"--working-directory", "--service-type", "--path-property", "--socket-property"}
            | {"--timer-property", "--on-active", "--on-boot", "--on-startup"}
            | {"--on-unit-active", "--on-unit-inactive", "--on-calendar"}
        )
    ),
    "firejail": _Wrapper(),
    "screen": _Wrapper(
        value_options=frozenset({"-S", "-c", "-e", "-h", "-p", "-s", "-t", "-T", "-X"})
    ),
    "xargs": _Wrapper(
        value_options=frozenset(
            {
                "-I",
                "-E",
                "-L",
                "-n",
                "-P",
                "-s",
                "-d",
                "-a",
                "--arg-file",
                "--delimiter",
                "--eof",
                "--max-args",
                "--max-chars",
                "--max-lines",
                "--max-procs",
                "--process-slot-var",
            }
        )
    ),
}


# The one redirect grammar (GH-1798): an optional fd number, then the
# operator. Whatever follows the operator in the same word is its target;
# a bare operator takes the next word. The scanner matches it against raw
# source, so a quoted or escaped `>` never reads as a redirect;
# `strip_command_wrappers` matches it against already-split tokens.
_REDIRECT_OPERATOR_RE = re.compile(r"\d*(?:<<<|<<-|<<|<>|<&|<|>>|>&|>\||>)|&>>|&>")
_HEREDOC_OPERATORS = frozenset({"<<", "<<-"})


def _bundle_value_index(*, token: str, value_options: frozenset[str]) -> int | None:
    """Index in ``token`` of a short-option bundle's first value letter.

    getopt ends a bundle at its first value-taking letter, and the rest of
    the token is that letter's value. ``None`` when ``token`` is not a
    bundle or carries no value letter.
    """
    if token.startswith("--") or not token.startswith("-") or len(token) < 2:
        return None
    for position, letter in enumerate(token[1:], start=1):
        if f"-{letter}" in value_options:
            return position
    return None


def _bundle_takes_next_value(*, token: str, value_options: frozenset[str]) -> bool:
    """True when a short-option bundle ends on a value option.

    ``sudo -iu postgres dropdb`` bundles ``-i`` with ``-u``; the bundle's
    last letter takes the next token. A value letter mid-bundle has its
    value attached (``-u5``), so nothing more is consumed.
    """
    if len(token) < 3:
        return False
    position = _bundle_value_index(token=token, value_options=value_options)
    return position == len(token) - 1


def _skip_options(*, parts: list[str], idx: int, value_options: frozenset[str]) -> int:
    while idx < len(parts) and parts[idx].startswith("-") and parts[idx] != "-":
        token = parts[idx]
        idx += 1
        if token == "--":
            break
        if token in value_options or _bundle_takes_next_value(
            token=token, value_options=value_options
        ):
            idx += 1
    return idx


def _split_string_value(
    *, token: str, following: str, wrapper: _Wrapper
) -> tuple[str, int] | None:
    """The command string ``token`` carries for a split option, and the
    number of words it spans, or ``None`` when it is not one.

    Covers ``--split-string X``, ``--split-string=X``, ``-S X``, ``-SX``
    and a bundle ending in or attaching to ``-S`` (``-iS X``, ``-iSX``).
    A bundle ends at its first value letter of any kind, so ``-uSTATE``
    unsets ``STATE`` rather than splitting ``TATE``.
    """
    options = wrapper.split_options
    if token.startswith("--"):
        name, equals, value = token.partition("=")
        if name not in options:
            return None
        return (value, 1) if equals else (following, 2)
    position = _bundle_value_index(token=token, value_options=wrapper.value_options | options)
    if position is None or f"-{token[position]}" not in options:
        return None
    attached = token[position + 1 :]
    return (attached, 1) if attached else (following, 2)


def _splice_split_strings(*, parts: list[str], idx: int, wrapper: _Wrapper) -> list[str]:
    """``parts`` with the first ``env -S`` string replaced by its words.

    Scans the wrapper's options from ``idx``. The spliced words are read
    as the wrapper's own arguments again, as ``env`` itself does.
    """
    scan = idx
    while scan < len(parts) and parts[scan].startswith("-") and parts[scan] != "--":
        token = parts[scan]
        following = parts[scan + 1] if scan + 1 < len(parts) else ""
        split = _split_string_value(token=token, following=following, wrapper=wrapper)
        if split is not None:
            command, consumed = split
            return [*parts[:scan], *split_tokens(command=command), *parts[scan + consumed :]]
        scan += 2 if token in wrapper.value_options else 1
    return parts


def _skip_wrapper_options(*, parts: list[str], idx: int, wrapper: _Wrapper) -> int:
    idx = _skip_options(parts=parts, idx=idx, value_options=wrapper.value_options)
    return min(idx + wrapper.positionals, len(parts))


def strip_command_wrappers(*, parts: list[str]) -> list[str]:
    """``parts`` from the program actually run, past env, wrappers and runners.

    ``FOO=1 timeout 30 nice -n 5 python -c …`` yields ``["python", "-c", …]``.
    Guards that judge ``parts[0]`` otherwise see ``timeout`` and abstain,
    which is the evasion GH-1630's review found for DX003 and DX004.
    ``sudo``, ``doas`` and ``xargs`` unwrap the same way (GH-1774), so
    ``sudo -u app python -c …`` is judged as the ``python`` call it is,
    and so do ``setsid``, ``pkexec``, ``chroot``, ``nsenter`` and the
    string ``env -S`` splits (GH-1798).
    A redirect may precede the program too: ``>/dev/null python -c …``.
    """
    return _wrapper_walk(parts=parts)[0]


def _wrapper_walk(*, parts: list[str]) -> tuple[list[str], list[list[str]]]:
    """The program's argv, and the argv from each wrapper stripped on the way."""
    stages: list[list[str]] = []
    idx = 0
    while idx < len(parts):
        token = parts[idx]
        if ANY_CASE_ENV_VAR_RE.match(token):
            idx += 1
            continue
        redirect = _REDIRECT_OPERATOR_RE.match(token)
        if redirect:
            # A bare operator (`>`, `2>`) takes the next word as its target.
            idx += 1 if token[redirect.end() :] else 2
            continue
        wrapper = _COMMAND_WRAPPERS.get(token.rsplit("/", 1)[-1])
        if wrapper is None:
            break
        if wrapper.split_options:
            parts = _splice_split_strings(parts=parts, idx=idx + 1, wrapper=wrapper)
        stages.append(parts[idx:])
        idx = _skip_wrapper_options(parts=parts, idx=idx + 1, wrapper=wrapper)
    return parts[idx:], stages


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


# Single- and double-quoted spans, quote-aware (GH-1350). A double-quoted
# span honours backslash-escaped quotes (`\"`) so it doesn't end early on
# `"she said \"hi\""`; both alternatives are DOTALL so a span embedding a
# real newline (a multi-line `-m` message, inline JSON/YAML) is captured
# whole rather than truncated at line end.
#
# Deliberately NOT used to feed command-substitution-depth checks: `$(...)`
# still executes inside double quotes in bash, so a caller counting nested
# substitutions must scan the ORIGINAL text there — this helper is for
# statement-separator counting (`;`, bare newline), where a literal
# separator character embedded in a quoted string is never a real shell
# boundary.
QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", re.DOTALL)

LINE_CONTINUATION_RE = re.compile(r"\\\n")


def strip_quoted_spans(*, command: str) -> str:
    """Replace every single- or double-quoted span with an empty pair.

    See ``QUOTED_SPAN_RE`` for why this is scoped to statement-separator
    counting rather than command-substitution detection.
    """
    return QUOTED_SPAN_RE.sub("''", command)


def strip_line_continuations(*, command: str) -> str:
    """Collapse a backslash-newline continuation into a single space.

    A command wrapped across lines with a trailing ``\\`` is one logical
    statement, not a bare-newline chain — join the halves before any
    newline-based separator counting runs.
    """
    return LINE_CONTINUATION_RE.sub(" ", command)


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
    nested ones re-scans each result (see :func:`command_units`).

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


@lru_cache(maxsize=_LEX_CACHE_SIZE)
def command_units(*, command: str, include_remote: bool = True) -> tuple[str, ...]:
    """``command`` plus every command it nests in a substitution (GH-986).

    A substitution runs its body as its own command, so each body is a
    unit a guard must judge on its own terms. Flatten once per check: the
    guards run on every Bash call under a CI latency benchmark, so
    re-deriving units per sub-check repeats the scan on ordinary commands.

    The sweep re-scans every body because ``substitution_bodies`` returns
    only the outermost ones; that is what reaches a nested
    ``$(python3 -c "$(echo x)")``. Shared by DX003 and DX004 (GH-1732).

    A runner that executes a command given as an argument (``ssh host
    '…'``, ``su -c '…'``, ``docker run img …``, ``find -exec …``) nests a
    unit the same way a substitution does (GH-1774). ``include_remote=False``
    leaves out what runs on another host or in a container, and everything
    nested inside it, for checks that judge local paths.
    """
    return tuple(
        unit.command
        for unit in tagged_command_units(command=command)
        if include_remote or not unit.remote
    )


@lru_cache(maxsize=_LEX_CACHE_SIZE)
def tagged_command_units(*, command: str) -> tuple[NestedCommand, ...]:
    """:func:`command_units`, each tagged with whether it runs remotely.

    One pass (GH-1798): a guard that needs both every unit and the remote
    flag used to flatten twice. A unit is remote when every path to it
    goes through ``ssh`` or a container; one local path makes it local,
    which is what flattening without the remote bodies used to decide.
    """
    remote_by_unit = {command: False}
    pending = [command]
    while pending:
        unit = pending.pop()
        parent_remote = remote_by_unit[unit]
        bodies = [
            *(
                NestedCommand(command=body, remote=parent_remote)
                for body in substitution_bodies(unit, include_backticks=True)
            ),
            *(
                NestedCommand(command=nested.command, remote=parent_remote or nested.remote)
                for nested in _runner_bodies(unit=unit)
            ),
        ]
        for body in bodies:
            if not body.command.strip():
                continue
            known = remote_by_unit.get(body.command)
            if known is None or (known and not body.remote):
                remote_by_unit[body.command] = body.remote
                pending.append(body.command)
    return tuple(
        NestedCommand(command=unit, remote=remote) for unit, remote in remote_by_unit.items()
    )


_PIPE_OPERATORS = frozenset({"|", "|&"})
# Openers the scanner emits as operator tokens, so the segmenter never
# guesses a substitution from the word before a `(`. A backtick both
# opens and closes; the segmenter tells the two apart.
_SUBSTITUTION_OPENERS = frozenset({"$(", "<(", ">(", "`"})
_PAREN_SUBSTITUTION_OPENERS = ("$(", "<(", ">(")
_PROCESS_SUBSTITUTION_REDIRECTS = {"<(": "<", ">(": ">"}
# How argv spells a word that is only a command substitution: its text is
# unknown until it runs, and the leading `$` tells a path guard so.
SUBSTITUTION_WORD = "$(...)"
# Where a substitution sits inside a raw argv word, until the segment is
# finalized. No shell word can hold a NUL, so command_segments drops any
# from its input and `$'\0'` decodes to nothing.
_SUBSTITUTION_MARK = "\0"
# Characters that start an operator ending one command (GH-1773). An
# unquoted newline ends a command the way `;` does.
_OPERATOR_CHARS = ";&|()\n"
_TWO_CHAR_OPERATORS = frozenset({";;", "&&", "||", "|&"})
# A set, not a string: after a quoted part `last_unquoted` is "", and
# `"" in "<>"` is True, which glued a background `&` onto `'a'&`.
_REDIRECT_CHARS = frozenset("<>")
# Not `\r`: bash does not split on it, so `git\rstatus` is one word.
_BLANKS = " \t"
_ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "e": "\x1b"}
_OCTAL_DIGITS = frozenset("01234567")
_OCTAL_ESCAPE_MAX_DIGITS = 3
# `$'\160ython3'` runs python3, and only the scanner decodes it, so a
# probe that misses the raw text looks again at the decoded words.
_OCTAL_ESCAPE = re.compile(r"\\[0-7]")
_DOUBLE_QUOTE_ESCAPES = '$`"\\\n'

# Reserved words that may open a segment without being the program it
# runs: `if dropdb x; then …` and `do ruff check $f` both run the word
# after the keyword. Process wrappers (`time`, `exec`, `command`) are not
# here; `strip_command_wrappers` owns them, options and all.
SHELL_KEYWORDS = frozenset({"!", "{", "}", "if", "then", "else", "elif", "while", "until", "do"})

# Compound commands a redirect can follow (GH-1876): `while …; done > f`
# writes `f` from every command inside. `for` and `case` stay in argv as
# their segment's first word; a closer is dropped like `}`, so the
# redirect lands on a program-less segment and reaches the enclosed ones.
_COMPOUND_OPENERS = {"if": "if", "while": "do", "until": "do", "for": "do", "case": "case"}
_COMPOUND_CLOSERS = {"fi": "if", "done": "do", "esac": "case"}


class UntokenizableCommandError(ValueError):
    """Raised when a command cannot be split into segments.

    Callers decide explicitly whether that fails closed (a safety guard
    falls back to :func:`command_position_re`) or abstains (a friction
    rule has no invocation to anchor on).
    """


@dataclass(frozen=True)
class Redirect:
    """One redirection: its operator (fd number included) and target word.

    A heredoc's target is its delimiter; the body never reaches a segment.
    """

    operator: str
    target: str = ""

    @property
    def writes(self) -> bool:
        """True for an output redirect (``>``, ``2>>``, ``&>``, ``>&2``)."""
        return ">" in self.operator

    @property
    def feeds_inline_text(self) -> bool:
        """True for a heredoc or here-string: stdin is text in the command."""
        return self.operator.lstrip("0123456789").startswith("<<")

    @property
    def touches_no_file(self) -> bool:
        """True for ``/dev/null`` or an fd duplicate (``2>&1``, ``>&-``).

        An auto-approval (GH-1795) may vouch only for these: any other
        redirect reads or writes a file no allow-rule named.
        """
        operator = self.operator.lstrip("0123456789")
        if operator in (">&", "<&"):
            return self.target.isdigit() or self.target == "-"
        return not self.feeds_inline_text and self.target == "/dev/null"


@dataclass(frozen=True)
class CommandSegment:
    """One simple command: its argv, its redirects, and its opener.

    Redirect words and their targets are kept out of ``argv`` (GH-1798),
    wherever they sit, so ``python >/dev/null -c x`` and ``>/dev/null
    python -c x`` give the same argv.
    """

    argv: tuple[str, ...]
    opener: str = ""
    redirects: tuple[Redirect, ...] = ()

    @property
    def is_piped(self) -> bool:
        """True when the segment reads the previous segment's output."""
        return self.opener in _PIPE_OPERATORS


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    is_operator: bool = False
    redirect: str = ""
    # Any quote or backslash escape in the word. A quoted word is never a
    # reserved word to the shell: `'}'` is a command, not a group close.
    quoted: bool = False
    # No blank between this token and the previous one: `a$(b)c` is one
    # shell word made of three tokens.
    glued: bool = False


class _Glue(Enum):
    """What a token glued to the previous one continues."""

    NONE = auto()
    WORD = auto()
    TARGET = auto()


class _WordState(Enum):
    START = auto()
    FD = auto()
    OPERATOR = auto()
    TARGET = auto()
    WORD = auto()
    BREAK = auto()


@dataclass
class _Scanner:
    """A quote-aware shell word scanner (GH-1773 review).

    shlex hands back ``';'`` and ``\\;`` as the same ``;`` token as a
    real operator, so a quoted or escaped operator split commands it
    did not end. This scanner marks a token as an operator only when
    the shell would: unquoted, unescaped, outside a word-internal
    redirect (``2>&1``, ``&>f``, ``>|f``). It also drops comments and
    heredoc bodies, which the shell never runs as commands here.
    """

    source: str
    index: int = 0

    def tokens(self) -> list[_Token]:
        tokens: list[_Token] = []
        heredocs: list[tuple[str, bool]] = []
        awaiting_delimiter: bool | None = None
        previous_end = -1
        while self.index < len(self.source):
            char = self.source[self.index]
            glued = self.index == previous_end
            if char in _BLANKS:
                self.index += 1
                continue
            if char == "\\" and self.source.startswith("\\\n", self.index):
                self.index += 2
                if glued:
                    previous_end = self.index
                continue
            if char == "#":
                self._skip_comment()
                continue
            if char == "`" or self.source.startswith(_PAREN_SUBSTITUTION_OPENERS, self.index):
                opener = "`" if char == "`" else self.source[self.index : self.index + 2]
                self.index += len(opener)
                tokens.append(_Token(text=opener, is_operator=True, glued=glued))
            elif char in _OPERATOR_CHARS and not self._is_redirect_ampersand():
                operator = self._operator()
                tokens.append(_Token(text=operator, is_operator=True, glued=glued))
                if operator == "\n" and heredocs:
                    self._skip_heredoc_bodies(heredocs=heredocs)
                    heredocs = []
            else:
                redirect = _REDIRECT_OPERATOR_RE.match(self.source, self.index)
                operator = redirect.group() if redirect else ""
                word, quoted = self._word()
                tokens.append(_Token(text=word, redirect=operator, quoted=quoted, glued=glued))
                heredoc_operator = operator.lstrip("0123456789")
                if awaiting_delimiter is not None:
                    heredocs.append((word, awaiting_delimiter))
                    awaiting_delimiter = None
                elif heredoc_operator in _HEREDOC_OPERATORS:
                    strip_tabs = heredoc_operator == "<<-"
                    delimiter = word[len(operator) :]
                    if delimiter:
                        heredocs.append((delimiter, strip_tabs))
                    else:
                        awaiting_delimiter = strip_tabs
            previous_end = self.index
        return tokens

    @staticmethod
    def _advance(*, state: _WordState, char: str) -> _WordState:
        if char in _REDIRECT_CHARS:
            if state in (_WordState.START, _WordState.FD, _WordState.OPERATOR):
                return _WordState.OPERATOR
            return _WordState.BREAK
        if char in "&|":
            # Only a glued `&`/`|` gets here: `&>` opens a word, `>&` and
            # `>|` continue an operator, and `a&>f` starts a new word.
            if state in (_WordState.START, _WordState.OPERATOR):
                return _WordState.OPERATOR
            return _WordState.BREAK
        if char.isdigit() and state in (_WordState.START, _WordState.FD):
            return _WordState.FD
        if state in (_WordState.OPERATOR, _WordState.TARGET):
            return _WordState.TARGET
        return _WordState.WORD

    def _skip_comment(self) -> None:
        end = self.source.find("\n", self.index)
        self.index = len(self.source) if end == -1 else end

    def _is_redirect_ampersand(self) -> bool:
        return self.source.startswith("&>", self.index)

    def _operator(self) -> str:
        pair = self.source[self.index : self.index + 2]
        if pair in _TWO_CHAR_OPERATORS:
            self.index += 2
            return pair
        self.index += 1
        return self.source[self.index - 1]

    def _word(self) -> tuple[str, bool]:
        """The next word with its quoting removed, and whether any was removed."""
        chars: list[str] = []
        last_unquoted = ""
        quoted = False
        # Where the word stands against the redirect grammar: still at its
        # start, inside a leading fd number, inside the operator, or past
        # it. An unquoted `<`/`>` after anything else ends the word, the
        # way bash reads `echo a>f` as `echo a` plus `>f` (GH-1798).
        state = _WordState.START
        while self.index < len(self.source):
            char = self.source[self.index]
            if char in _BLANKS or char == "`" or self.source.startswith("$(", self.index):
                break
            if char in _OPERATOR_CHARS:
                glued = (
                    char == "&"
                    and (last_unquoted in _REDIRECT_CHARS or self._is_redirect_ampersand())
                ) or (char == "|" and last_unquoted == ">")
                if not glued:
                    break
            state = self._advance(state=state, char=char)
            if state is _WordState.BREAK:
                break
            if char == "\\":
                if self.source.startswith("\\\n", self.index):
                    self.index += 2
                    continue
                chars.append(self.source[self.index + 1 : self.index + 2])
                self.index += 2
                last_unquoted = ""
                quoted = True
            elif char == "$" and self.source.startswith("$'", self.index):
                chars.append(self._ansi_c_quoted())
                last_unquoted = ""
                quoted = True
            elif char == "'":
                chars.append(self._single_quoted())
                last_unquoted = ""
                quoted = True
            elif char == '"':
                chars.append(self._double_quoted())
                last_unquoted = ""
                quoted = True
            else:
                chars.append(char)
                self.index += 1
                last_unquoted = char
        return "".join(chars), quoted

    def _single_quoted(self) -> str:
        end = self.source.find("'", self.index + 1)
        if end == -1:
            raise UntokenizableCommandError("unterminated single quote")
        text = self.source[self.index + 1 : end]
        self.index = end + 1
        return text

    def _ansi_c_quoted(self) -> str:
        """``$'…'``: a backslash escapes the next character, ``\\'`` included.

        Reading it as a plain single-quoted span ends it at ``\\'``, and the
        quote parity then disagrees with bash: ``$'\\''; rm -rf ~; $'\\''``
        is two operators to bash and one argument to a naive scanner
        (GH-1795 review). Escapes are decoded only as far as a guard needs.
        A NUL ends the word, as it does for bash: ``$'rm\\0junk'`` runs
        ``rm``. No shell word can hold a NUL, and the segmenter uses NUL
        as its own substitution mark.
        """
        chars: list[str] = []
        truncated = False
        self.index += 2
        while self.index < len(self.source):
            char = self.source[self.index]
            if char == "'":
                self.index += 1
                return "".join(chars)
            if char == "\\" and self.index + 1 < len(self.source):
                decoded = self._ansi_c_escape()
            else:
                decoded = char
                self.index += 1
            truncated = truncated or decoded == "\0"
            if not truncated:
                chars.append(decoded)
        raise UntokenizableCommandError("unterminated ANSI-C quote")

    def _ansi_c_escape(self) -> str:
        escaped = self.source[self.index + 1]
        if escaped not in _OCTAL_DIGITS:
            self.index += 2
            return _ANSI_C_ESCAPES.get(escaped, escaped)
        end = self.index + 1
        limit = min(end + _OCTAL_ESCAPE_MAX_DIGITS, len(self.source))
        while end < limit and self.source[end] in _OCTAL_DIGITS:
            end += 1
        digits = self.source[self.index + 1 : end]
        self.index = end
        return chr(int(digits, 8) & 0xFF)

    def _double_quoted(self) -> str:
        chars: list[str] = []
        self.index += 1
        while self.index < len(self.source):
            char = self.source[self.index]
            if char == '"':
                self.index += 1
                return "".join(chars)
            following = self.source[self.index + 1 : self.index + 2]
            if char == "\\" and following and following in _DOUBLE_QUOTE_ESCAPES:
                chars.append("" if following == "\n" else following)
                self.index += 2
                continue
            chars.append(char)
            self.index += 1
        raise UntokenizableCommandError("unterminated double quote")

    def _skip_heredoc_bodies(self, *, heredocs: list[tuple[str, bool]]) -> None:
        for delimiter, strip_tabs in heredocs:
            while self.index < len(self.source):
                end = self.source.find("\n", self.index)
                line_end = len(self.source) if end == -1 else end
                line = self.source[self.index : line_end]
                self.index = line_end + 1 if end != -1 else line_end
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break


@lru_cache(maxsize=_LEX_CACHE_SIZE)
def command_segments(*, command: str) -> tuple[CommandSegment, ...]:
    """Split ``command`` into simple commands on every shell operator (GH-1773).

    Quote-aware: an operator that is quoted or escaped (``';'``, ``\\;``)
    stays an argument, and ``&`` inside a redirect (``2>&1``, ``&>f``)
    stays part of it. Splits on ``;``, ``&``, ``&&``, ``|``, ``||``,
    ``|&``, ``(``, ``)`` and newlines, drops comments and heredoc bodies,
    and drops a leading reserved word (:data:`SHELL_KEYWORDS`).
    Redirects go to :attr:`CommandSegment.redirects`, never to ``argv``.
    A redirect on a command group or subshell — ``{ echo hi; } > f``,
    ``(cat a b) > f`` — is also attributed to every segment inside the
    group (GH-1816): the shell applies it to the group as a whole, and a
    guard judging the verb would otherwise see a program-less trailing
    segment and nothing on ``echo``. The trailing segment stays, so a
    caller counting segments sees the same shape as before. A compound
    command is a group the same way (GH-1876): ``if …; fi > f``,
    ``while``/``until``/``for …; done > f`` and ``case …; esac > f``
    attribute ``f`` to every segment from the opening keyword's on,
    and ``fi``/``done``/``esac`` leave ``argv`` like ``}`` does.
    The scanner emits ``$(``, ``<(``, ``>(`` and backticks as operators
    (GH-1876). The command holding a substitution is one segment, before
    the body's: the words and redirects after the substitution continue
    it, so ``echo $(date) more > f`` is one ``echo`` writing ``f``. How a
    command substitution reads in ``argv`` is set by
    :func:`_finalized_argv`. A process substitution is kept as a
    target-less redirect (``cat <(a)``), and a substitution after a
    redirect operator is part of its target (``cat < <(a)`` reads
    ``<(``). A reserved word in case-pattern position is a pattern
    (``a|if)``). A closer with no matching opener, a quoted brace or
    keyword, and a ``)`` that ends a ``case`` pattern attribute nothing.
    Substitution bodies are not unwrapped here; :func:`command_units`
    hands each one over as its own command.

    Raises :class:`UntokenizableCommandError` on an unbalanced quote.
    Skipping such input silently was the evasion this function replaces,
    so every caller must choose its fallback.
    """
    source = command.replace(_SUBSTITUTION_MARK, "")
    return _Segmenter().run(tokens=_Scanner(source=source).tokens())


@dataclass
class _Segmenter:
    """The state machine behind :func:`command_segments`."""

    segments: list[CommandSegment] = field(default_factory=list)
    argv: list[str] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    opener: str = ""
    bare_operator: str | None = None
    # Open groups, innermost last: the opener and the index of the first
    # segment inside it. A substitution entry (`$`, or a backtick)
    # carries the index of the command that holds it instead. `if`, `do`
    # and `case` entries are compound commands; `case` also tells a
    # pattern's `)` apart from a subshell close.
    open_groups: list[tuple[str, int]] = field(default_factory=list)
    closed_group: tuple[int, int] | None = None
    # The command a closed substitution sits in. The words and redirects
    # after it continue that command: `echo $(date) more > f` runs `echo`
    # with `more` and writes `f` through it.
    resumed: int | None = None
    # Per open substitution's holder: its raw argv (with _SUBSTITUTION_MARK
    # where the substitution sits) and what a glued token after it extends.
    held: dict[int, tuple[list[str], _Glue]] = field(default_factory=dict)
    # What a token glued to the previous one extends: `a$(b)c` is one argv
    # word, `>o$(b)` one redirect target.
    glue: _Glue = _Glue.NONE
    # The next word is a case pattern, where `if)` names a pattern and
    # opens nothing; only `esac` keeps its meaning there.
    case_pattern: bool = False
    # The current segment is a case pattern list, so `|` starts another
    # pattern: `a|if)`.
    pattern_list: bool = False
    last_operator: str = ""

    def run(self, *, tokens: list[_Token]) -> tuple[CommandSegment, ...]:
        for token in tokens:
            if token.is_operator:
                self._operator(token=token)
            else:
                self._word(token=token)
        if self.bare_operator is not None:
            self.redirects.append(Redirect(operator=self.bare_operator))
        self._flush(next_opener="")
        return tuple(self.segments)

    def _current(self) -> CommandSegment:
        return CommandSegment(
            argv=_finalized_argv(argv=self.argv),
            opener=self.opener,
            redirects=tuple(self.redirects),
        )

    def _flush(self, *, next_opener: str) -> None:
        if self.redirects and self.closed_group is not None and not self.argv:
            _attribute_group_redirects(
                segments=self.segments, group=self.closed_group, redirects=self.redirects
            )
        self.closed_group = None
        self.pattern_list = False
        if self.resumed is not None:
            self.segments[self.resumed] = self._current()
            self.resumed = None
        elif self.argv or self.redirects:
            self.segments.append(self._current())
        elif self.opener in _PIPE_OPERATORS:
            return
        self.argv = []
        self.redirects = []
        self.opener = next_opener

    def _operator(self, *, token: _Token) -> None:
        if token.text == "`" and self._innermost_group() == "`":
            self._close_substitution()
            return
        if token.text in _SUBSTITUTION_OPENERS:
            self.case_pattern = False
            self._open_substitution(opener=token.text, glued=token.glued)
            return
        self.glue = _Glue.NONE
        if self.bare_operator is not None:
            self.redirects.append(Redirect(operator=self.bare_operator))
            self.bare_operator = None
        if token.text == ")" and self._innermost_group() == "$(":
            self.case_pattern = False
            self._close_substitution()
            return
        # A newline ends a command the way `;` does.
        operator = ";" if token.text == "\n" else token.text
        self.case_pattern = self._pattern_follows(operator=operator)
        self.last_operator = operator
        self._flush(next_opener=operator)
        if operator == "(":
            self.open_groups.append(("(", len(self.segments)))
        elif operator == ")":
            self.closed_group = _close_group(
                open_groups=self.open_groups, closers=("(",), end=len(self.segments)
            )

    def _innermost_group(self) -> str:
        return self.open_groups[-1][0] if self.open_groups else ""

    def _pattern_follows(self, *, operator: str) -> bool:
        """True when the word after ``operator`` is a case pattern.

        A pattern follows ``;;``, ``;&`` and ``;;&``, the ``|`` of a
        pattern list, a ``case … in`` header, and the ``(`` that may open
        a pattern. A blank line between them changes nothing.
        """
        nothing_pending = not self.argv and not self.redirects
        header = self.argv[:1] == ["case"] and self.argv[2:3] == ["in"]
        if operator == "|":
            return self.pattern_list or (header and len(self.argv) > 3)
        if self._innermost_group() != "case":
            return False
        if operator == ";;":
            return True
        if operator == "&":
            return nothing_pending and self.last_operator in (";", ";;")
        if operator in (";", "("):
            ends_header = header and len(self.argv) == 3
            return ends_header or (nothing_pending and self.case_pattern)
        return False

    def _open_substitution(self, *, opener: str, glued: bool) -> None:
        """Store the command holding the substitution, then read its body.

        The holder is written now, so the body's segments follow it. A
        substitution right after a redirect operator, or glued to its
        target, is part of that target (``cat < <(a)``, ``>o$(a)``).
        Anywhere else a process substitution is a file the command reads
        or writes, kept as a target-less redirect, and a command
        substitution is a word (see :func:`_finalized_argv`).
        """
        glue, self.glue = self.glue, _Glue.NONE
        after = _Glue.NONE
        if self.bare_operator is not None:
            self.redirects.append(Redirect(operator=self.bare_operator, target=opener))
            self.bare_operator = None
            after = _Glue.TARGET
        elif glued and glue is _Glue.TARGET:
            self._extend_target(text=opener)
            after = _Glue.TARGET
        elif opener in _PROCESS_SUBSTITUTION_REDIRECTS:
            self.redirects.append(Redirect(operator=_PROCESS_SUBSTITUTION_REDIRECTS[opener]))
        elif glued and glue is _Glue.WORD:
            self.argv[-1] += _SUBSTITUTION_MARK
            after = _Glue.WORD
        else:
            self.argv.append(_SUBSTITUTION_MARK)
            after = _Glue.WORD
        self.closed_group = None
        if self.resumed is None:
            holder = len(self.segments)
            self.segments.append(self._current())
        else:
            holder = self.resumed
            self.segments[holder] = self._current()
            self.resumed = None
        self.held[holder] = (list(self.argv), after)
        self.open_groups.append(("`" if opener == "`" else "$(", holder))
        self.argv = []
        self.redirects = []
        self.opener = opener

    def _close_substitution(self) -> None:
        if self.bare_operator is not None:
            self.redirects.append(Redirect(operator=self.bare_operator))
            self.bare_operator = None
        self._flush(next_opener="")
        _, holder = self.open_groups.pop()
        self.argv, self.glue = self.held.pop(holder)
        held = self.segments[holder]
        self.redirects = list(held.redirects)
        self.opener = held.opener
        self.resumed = holder

    def _extend_target(self, *, text: str) -> None:
        last = self.redirects[-1]
        self.redirects[-1] = replace(last, target=last.target + text)

    def _word(self, *, token: _Token) -> None:
        glue, self.glue = self.glue, _Glue.NONE
        case_pattern, self.case_pattern = self.case_pattern, False
        if self.bare_operator is not None:
            self.redirects.append(Redirect(operator=self.bare_operator, target=token.text))
            self.bare_operator = None
            self.glue = _Glue.TARGET
            return
        if token.glued and glue is _Glue.TARGET and not token.redirect:
            self._extend_target(text=token.text)
            self.glue = _Glue.TARGET
            return
        if token.redirect:
            target = token.text[len(token.redirect) :]
            if target:
                self.redirects.append(Redirect(operator=token.redirect, target=target))
                self.glue = _Glue.TARGET
            else:
                self.bare_operator = token.redirect
            return
        # A reserved word counts only where a command starts: unquoted,
        # first in its segment, and not continuing a command after a
        # substitution (`echo $(date) case` passes `case` to echo).
        starts_command = (
            not self.argv
            and not token.quoted
            and self.resumed is None
            and not (case_pattern and token.text != "esac")
        )
        if starts_command and token.text in _COMPOUND_CLOSERS:
            self.closed_group = _close_group(
                open_groups=self.open_groups,
                closers=(_COMPOUND_CLOSERS[token.text],),
                end=len(self.segments),
            )
            return
        if starts_command and token.text in _COMPOUND_OPENERS:
            self.open_groups.append((_COMPOUND_OPENERS[token.text], len(self.segments)))
        if starts_command and token.text in SHELL_KEYWORDS:
            if token.text == "{":
                self.open_groups.append(("{", len(self.segments)))
            elif token.text == "}":
                self.closed_group = _close_group(
                    open_groups=self.open_groups, closers=("{",), end=len(self.segments)
                )
            return
        self.closed_group = None
        if token.glued and glue is _Glue.WORD:
            self.argv[-1] += token.text
        else:
            self.argv.append(token.text)
        self.pattern_list = self.pattern_list or case_pattern
        self.glue = _Glue.WORD


def _finalized_argv(*, argv: list[str]) -> tuple[str, ...]:
    """``argv`` with each command substitution spelled for a guard.

    A substitution's output is unknown, so a guard is shown the literal
    text it can still judge. A word that is only substitutions becomes
    :data:`SUBSTITUTION_WORD` and keeps its slot (``cp $(a) dest`` has two
    operands). One glued inside a word keeps the marker (``docs/$(a).py``
    still ends in ``.py``), while one at a word's edge is dropped
    (``$(a)psql`` runs ``psql``, ``x.py$(a)`` writes ``x.py``). Leading
    substitution-only words are dropped too, so ``$(a) cp x y`` is judged
    as the ``cp`` it may well run.
    """
    start = 0
    while start < len(argv) and argv[start] and not argv[start].strip(_SUBSTITUTION_MARK):
        start += 1
    return tuple(_finalized_word(word=word) for word in argv[start:])


def _finalized_word(*, word: str) -> str:
    if _SUBSTITUTION_MARK not in word:
        return word
    literal = word.strip(_SUBSTITUTION_MARK)
    if not literal:
        return SUBSTITUTION_WORD
    return literal.replace(_SUBSTITUTION_MARK, SUBSTITUTION_WORD)


def _close_group(
    *, open_groups: list[tuple[str, int]], closers: tuple[str, ...], end: int
) -> tuple[int, int] | None:
    """Pop the innermost group when ``closers`` names its opener.

    Returns the segment range a redirect after the closer applies to. A
    closer with no matching opener — a stray ``}``, a ``)`` closing a
    ``{``, or the ``)`` that ends a ``case`` pattern — pops nothing and
    returns None.
    """
    if not open_groups or open_groups[-1][0] not in closers:
        return None
    _, start = open_groups.pop()
    return start, end


def _attribute_group_redirects(
    *, segments: list[CommandSegment], group: tuple[int, int], redirects: list[Redirect]
) -> None:
    """Add a group's redirects to every segment the group encloses.

    Over-approximates on purpose: ``{ a | b; } > f`` redirects only
    ``b``'s stdout, but a guard that sees the redirect on ``a`` too can
    only block more, never less (GH-1816).
    """
    start, end = group
    added = tuple(redirects)
    for index in range(start, end):
        segment = segments[index]
        segments[index] = replace(segment, redirects=segment.redirects + added)


def is_simple_command(*, command: str) -> bool:
    """True when ``command`` runs exactly one command and touches no file.

    The precondition for an auto-approval that matched a rule against the
    whole string (GH-1795): `foo && rm -rf ~` starts with an allowed `foo`
    but runs two commands, and `foo > ~/.bashrc` writes a file the rule
    never named. One segment, no substitution, no runner body, only
    redirects that touch no file, and tokenizable, or it is not simple.
    """
    if len(command_units(command=command)) != 1:
        return False
    try:
        segments = command_segments(command=command)
    except UntokenizableCommandError:
        return False
    return len(segments) == 1 and all(r.touches_no_file for r in segments[0].redirects)


def segment_programs(*, command: str) -> list[tuple[CommandSegment, list[str]]]:
    """Each segment of ``command`` with the argv of the program it runs.

    Wrappers, runners and env assignments are stripped
    (:func:`strip_command_wrappers`), and a segment that runs nothing
    (``FOO=1``, ``> f``) is skipped. This is the loop every guard used to
    write for itself (GH-1798).

    Raises :class:`UntokenizableCommandError` like :func:`command_segments`,
    so a caller picks its own fallback.
    """
    return [
        (segment, parts)
        for segment in command_segments(command=command)
        if (parts := strip_command_wrappers(parts=list(segment.argv)))
    ]


# A command boundary: start of input, a shell operator, or the opening
# quote of a word (the command string `su -c '…` or `ssh host '…` runs).
_COMMAND_BOUNDARY = r"(?:^|[|;&(\n{]|\s['\"])\s*"
_ENV_ASSIGNMENTS = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
# Redirects ahead of the program, attached (`2>/dev/null`) or bare
# (`> out`), as `strip_command_wrappers` skips them on the tokenized path.
_LEADING_REDIRECTS = r"(?:(?:\d+|&)?[<>][<>&|]*(?:\S+|\s+\S+)\s+)*"
_WRAPPER_NAMES = "|".join(sorted(_COMMAND_WRAPPERS))
_DIRECTORY = r"(?:[\w./~-]*/)?"
# An option with at most one value word, so `sudo -u app` and
# `timeout 30` are both seen past. Over-reading a word is the safe
# direction here: the program can still match after it.
_WRAPPER_OPTIONS = r"(?:(?:-\S*|\d\S*)\s+(?:[^\s|;&-]\S*\s+)?)*"
_WRAPPER_PREFIX = (
    rf"(?:{_DIRECTORY}(?:{_WRAPPER_NAMES})\s+{_WRAPPER_OPTIONS}"
    rf"|{_DIRECTORY}ssh\s+{_WRAPPER_OPTIONS}[^\s|;&-]\S*\s+{_WRAPPER_OPTIONS})*"
)


def command_position_re(*, program: str) -> re.Pattern[str]:
    """Match ``program`` in command position, not as an argument (GH-971).

    ``program`` is a regex fragment. The match must follow a command
    boundary, optionally behind env assignments, wrappers, runners and
    their option values (``sudo -u app``, ``timeout 30``, ``ssh host``)
    and a directory prefix (``/bin/sh``). A bare word search would also
    match a filename argument such as ``bin/x.sh``.

    This is the fail-closed fallback for :class:`UntokenizableCommandError`,
    which is why it also treats an opening quote as a boundary: an
    unbalanced quote usually sits in the command string a runner was
    handed (``su -c 'dropdb x``). It over-matches by design.
    """
    return re.compile(
        _COMMAND_BOUNDARY
        + _LEADING_REDIRECTS
        + _ENV_ASSIGNMENTS
        + _WRAPPER_PREFIX
        + _DIRECTORY
        + r"(?:"
        + program
        + r")\b"
    )


@dataclass(frozen=True)
class NestedCommand:
    """A command a runner executes, and whether it runs on another host.

    ``remote`` marks a command run over ``ssh`` or inside a container,
    where a path names the remote filesystem, not this checkout.
    """

    command: str
    remote: bool = False
    # Typed keystrokes that move the cursor or recall history, so the
    # line the shell runs cannot be rebuilt from `command` (GH-2001).
    opaque: bool = False


_SSH_VALUE_OPTIONS = frozenset(
    {"-B", "-b", "-c", "-D", "-E", "-e", "-F", "-I", "-i", "-J", "-L", "-l", "-m"}
    | {"-O", "-o", "-p", "-Q", "-R", "-S", "-W", "-w"}
)
_OP_RUN_VALUE_OPTIONS = frozenset({"--env-file", "--environment"})
# CLIs that run a command in a container or pod. Their subcommands and
# option sets are too many to parse, so every argument suffix that starts
# at a plain word is judged as a candidate command: `docker run --rm img
# dropdb x` yields `dropdb x` among its candidates.
_CONTAINER_CLIS = frozenset({"docker", "podman", "nerdctl", "kubectl", "oc"})
_SU_RUNNERS = frozenset({"su", "runuser"})
_SU_COMMAND_OPTIONS = frozenset({"-c", "--command", "--session-command"})
_FIND_EXEC_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_EXEC_TERMINATORS = frozenset({";", "+"})
# Runners that re-read their arguments as one shell command line
# (GH-1798): `eval` and `watch` join them; `flock` takes a `-c` string or
# runs the words after its lock file.
_FLOCK_VALUE_OPTIONS = frozenset({"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"})
_FLOCK_COMMAND_OPTIONS = frozenset({"-c", "--command"})
_WATCH_VALUE_OPTIONS = frozenset({"-n", "--interval", "-q", "--equexit"})
# Search tools with an option naming a program they run (GH-1809):
# `rg --pre psql pattern` runs psql on every file it searches.
_PROGRAM_OPTIONS: dict[str, frozenset[str]] = {
    "rg": frozenset({"--pre", "--hostname-bin"}),
    "ag": frozenset({"--pager"}),
    "ack": frozenset({"--pager"}),
    "man": frozenset({"-P", "--pager"}),
    # `script -c 'cmd'` runs a command string (GH-1998).
    "script": frozenset({"-c", "--command"}),
}
# tmux subcommands whose trailing words are a shell command (GH-1998).
_TMUX_COMMAND_SUBCOMMANDS = frozenset(
    {"new-session", "new", "new-window", "neww", "split-window", "splitw"}
    | {"respawn-pane", "respawnp", "respawn-window", "respawnw", "run-shell", "run"}
    | {"send-keys", "send"}
)
_TMUX_VALUE_OPTIONS = frozenset(
    {"-c", "-e", "-F", "-n", "-s", "-t", "-x", "-y", "-l", "-f", "-L", "-S", "-N"}
)
# Keystroke runners (GH-2001): `tmux send-keys` and `screen -X stuff`
# type into a shell, so the typed line is a command. tmux's own `-c`
# (before any subcommand) runs a shell command too.
_LEGACY_TMUX_KEY_NAMES = frozenset({"Enter", "C-m", "KPEnter"})
# tmux resolves an alias, a full name or an unambiguous prefix
# (`send-k`) to a command, so names are canonicalized before matching.
_TMUX_ALIASES = {
    "send": "send-keys",
    "new": "new-session",
    "neww": "new-window",
    "splitw": "split-window",
    "respawnp": "respawn-pane",
    "respawnw": "respawn-window",
    "run": "run-shell",
    "setb": "set-buffer",
    "pasteb": "paste-buffer",
    "popup": "display-popup",
    "if": "if-shell",
    "pipep": "pipe-pane",
    "bind": "bind-key",
    "confirm": "confirm-before",
    "menu": "display-menu",
}
_TMUX_COMMAND_NAMES = frozenset(_TMUX_ALIASES.values()) | {
    "command-prompt",
    "set-hook",
    "load-buffer",
}
_TMUX_SHELL_COMMANDS = frozenset(
    {"new-session", "new-window", "split-window", "respawn-pane", "respawn-window", "run-shell"}
)
_TMUX_SEND_KEYS = "send-keys"
_TMUX_SET_BUFFER = "set-buffer"
_TMUX_SEND_VALUE_OPTIONS = frozenset({"-c", "-N", "-t"})
_TMUX_SET_BUFFER_VALUE_OPTIONS = frozenset({"-b", "-n", "-t"})
# An unparseable -H word: typed as a control key, so the line turns opaque.
_UNKNOWN_KEY = "\x00"
_TMUX_GLOBAL_COMMAND_OPTIONS = frozenset({"-c"})
_TMUX_GLOBAL_VALUE_OPTIONS = frozenset({"-c", "-f", "-L", "-S", "-T"})
_TMUX_SERVER_OPTIONS = frozenset({"-L", "-S"})
_TMUX_TARGET_OPTIONS = frozenset({"-t", "-b"})
_SCREEN_TARGET_OPTIONS = frozenset({"-S", "-p"})
# Units are visited in stack order, not text order, so up to this many
# typing units are replayed in every order (4! = 24 lines at most).
_MAX_REORDERED_UNITS = 4
_TMUX_SEPARATOR = ";"
_LINE_END_KEYS = frozenset(
    {"Enter", "C-m", "C-M", "C-j", "C-J", "KPEnter", "^M", "^J", "\n", "\r"}
)
_BLANK_KEYS = {"Space": " ", "Tab": "\t", "C-i": "\t", "^I": "\t", "\t": "\t"}
_ERASE_KEYS = frozenset({"BSpace", "C-h", "C-H", "^H", "C-?", "^?", "\b", "\x7f"})
_KILL_LINE_KEYS = frozenset({"C-c", "C-C", "C-u", "C-U", "^C", "^U", "\x03", "\x15"})
_NAMED_KEYS = frozenset(
    {"Up", "Down", "Left", "Right", "Home", "End", "Escape", "BTab", "DC", "IC"}
    | {"Delete", "Insert", "NPage", "PPage", "PageDown", "PageUp", "PgDn", "PgUp"}
)
_MODIFIED_KEY_RE = re.compile(r"^(?:[CMS]-)+.+$|^\^.$|^F\d{1,2}$")
_SCREEN_STUFF = "stuff"
_SCREEN_EVAL = "eval"
_SCREEN_REGISTER = "register"
_SCREEN_REGISTER_VALUE_OPTIONS = frozenset({"-e"})
_SCREEN_ESCAPE_RE = re.compile(r"\\([0-7]{1,3})|\\(.)|\^(.)", re.DOTALL)
_SCREEN_BACKSLASH_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "e": "\x1b", "a": "\a"}
_ASCII_CONTROL_MASK = 0x1F
_HEX_BASE = 16
_OCTAL_BASE = 8
_PARALLEL_VALUE_OPTIONS = frozenset(
    {"-j", "--jobs", "-S", "--sshlogin", "-a", "--arg-file", "-d", "--delimiter"}
    | {"-E", "-I", "--colsep", "-C", "--joblog", "--results", "--tmpdir", "-n", "-N"}
    | {"-L", "-P", "--timeout", "--delay"}
)
_PARALLEL_SEPARATORS = frozenset({":::", "::::", ":::+", "::::+"})
_RUNNER_NAMES = "|".join(
    sorted(
        {
            "ssh",
            "op",
            "find",
            "eval",
            "watch",
            "flock",
            "gdb",
            "tmux",
            "screen",
            "git",
            "parallel",
            *_CONTAINER_CLIS,
            *_SU_RUNNERS,
            *_PROGRAM_OPTIONS,
        }
    )
)
_SHELL_QUOTING = str.maketrans("", "", "\"'\\")


def without_shell_quoting(*, text: str) -> str:
    """``text`` minus quote and escape characters, for word probes.

    ``s''sh`` and ``b\\q`` run ``ssh`` and ``bq`` while the raw text names
    neither, so a probe that gates a check must search this instead.
    """
    return text.translate(_SHELL_QUOTING)


@dataclass(frozen=True)
class ProgramProbe:
    """A cheap gate: could ``command`` run ``program`` at all? (GH-1798)

    Each guard used to pick its own spelling: a raw substring
    (``"python" in command``), a ``\\b…\\b`` regex, or a quote-stripped
    search. The rule lives here instead:

    - quoting is dropped first, so ``p''ython`` and ``b\\q`` are seen;
    - no leading boundary, because ``su u -c'bq query'`` reads ``-cbq``
      once its quotes are gone;
    - a trailing boundary, so ``bq`` does not wake on ``bqtool``.

    A probe only decides whether the structured check runs, so an
    over-match costs one lexer pass and never a false block.
    """

    pattern: re.Pattern[str]

    @classmethod
    def for_program(cls, *, program: str) -> ProgramProbe:
        """Probe for ``program``, a regex fragment (alternatives allowed)."""
        return cls(pattern=re.compile(rf"(?:{program})\b"))

    def found_in(self, *, command: str) -> bool:
        if self.pattern.search(without_shell_quoting(text=command)):
            return True
        return _has_ansi_c_octal_escape(command=command) and self._found_in_decoded(
            command=command
        )

    def _found_in_decoded(self, *, command: str) -> bool:
        try:
            segments = command_segments(command=command)
        except UntokenizableCommandError:
            return True
        return any(self.pattern.search(word) for segment in segments for word in segment.argv)


def _has_ansi_c_octal_escape(*, command: str) -> bool:
    start = command.find("$'")
    return start != -1 and _OCTAL_ESCAPE.search(command, start + 2) is not None


_RUNNER_PROBE = ProgramProbe.for_program(program=_RUNNER_NAMES)


def _ssh_command(*, parts: list[str]) -> str:
    idx = _skip_options(parts=parts, idx=1, value_options=_SSH_VALUE_OPTIONS)
    # OpenSSH accepts options after the host too: `ssh db01 -t cmd`.
    idx = _skip_options(parts=parts, idx=idx + 1, value_options=_SSH_VALUE_OPTIONS)
    return " ".join(parts[idx:])


def _op_run_command(*, parts: list[str]) -> str:
    idx = _skip_options(parts=parts, idx=1, value_options=_OP_RUN_VALUE_OPTIONS)
    if idx >= len(parts) or parts[idx] != "run":
        return ""
    idx = _skip_options(parts=parts, idx=idx + 1, value_options=_OP_RUN_VALUE_OPTIONS)
    return shlex.join(parts[idx:])


def _container_commands(*, parts: list[str]) -> list[str]:
    if "--" in parts:
        tail = parts[parts.index("--") + 1 :]
        return [shlex.join(tail)] if tail else []
    words = parts[1:]
    return [
        shlex.join(words[start:])
        for start, word in enumerate(words)
        if not word.startswith("-") and "=" not in word
    ]


def _su_command(*, parts: list[str]) -> str:
    for idx, token in enumerate(parts[1:], start=1):
        following = parts[idx + 1] if idx + 1 < len(parts) else ""
        if token in _SU_COMMAND_OPTIONS:
            return following
        name, _, value = token.partition("=")
        if value and name in _SU_COMMAND_OPTIONS:
            return value
        position = _bundle_value_index(token=token, value_options=_SU_COMMAND_OPTIONS)
        if position is not None:
            # `-lc 'cmd'` bundles `-c` last; `-c'cmd'` attaches its value.
            return token[position + 1 :] or following
    return ""


def _flock_command_option(*, token: str, following: str) -> str | None:
    if token in _FLOCK_COMMAND_OPTIONS:
        return following
    name, _, value = token.partition("=")
    if value and name in _FLOCK_COMMAND_OPTIONS:
        return value
    return None


def _flock_command(*, parts: list[str]) -> str:
    idx = 1
    while idx < len(parts) and parts[idx].startswith("-") and parts[idx] != "-":
        token = parts[idx]
        idx += 1
        following = parts[idx] if idx < len(parts) else ""
        command = _flock_command_option(token=token, following=following)
        if command is not None:
            return command
        if token == "--":
            break
        if token in _FLOCK_VALUE_OPTIONS:
            idx += 1
    # The lock file, then either `-c 'cmd'` or the command's own words.
    rest = parts[idx + 1 :]
    if rest:
        command = _flock_command_option(token=rest[0], following=rest[1] if len(rest) > 1 else "")
        if command is not None:
            return command
    return shlex.join(rest)


def _watch_command(*, parts: list[str]) -> str:
    idx = _skip_options(parts=parts, idx=1, value_options=_WATCH_VALUE_OPTIONS)
    return " ".join(parts[idx:])


def _attached_short_value(*, token: str, options: frozenset[str]) -> str | None:
    """``psql`` for ``-Ppsql`` when ``-P`` is a short option in ``options``."""
    if token.startswith("--") or len(token) <= 2:
        return None
    return token[2:] if token[:2] in options else None


def _program_option_commands(*, parts: list[str], options: frozenset[str]) -> list[str]:
    commands: list[str] = []
    for idx, token in enumerate(parts[1:], start=1):
        attached = _attached_short_value(token=token, options=options)
        if attached is not None:
            commands.append(attached)
            continue
        name, equals, value = token.partition("=")
        if name not in options:
            continue
        if equals:
            commands.append(value)
        elif idx + 1 < len(parts):
            commands.append(parts[idx + 1])
    return commands


def _gdb_command(*, parts: list[str]) -> str:
    if "--args" not in parts:
        return ""
    return shlex.join(parts[parts.index("--args") + 1 :])


@dataclass
class _TypedLine:
    """The text a terminal holds after a stream of keystrokes."""

    text: list[str]
    opaque: bool = False

    def press(self, *, key: str) -> None:
        if key in _LINE_END_KEYS:
            self.text.append("\n")
        elif key in _BLANK_KEYS:
            self.text.append(_BLANK_KEYS[key])
        elif key in _ERASE_KEYS:
            if self.text and self.text[-1] != "\n":
                self.text.pop()
        elif key in _KILL_LINE_KEYS:
            while self.text and self.text[-1] != "\n":
                self.text.pop()
        elif key in _NAMED_KEYS or _MODIFIED_KEY_RE.match(key) or _is_control(key=key):
            self.opaque = True
        else:
            self.text.extend(key)

    def nested(self) -> NestedCommand:
        return NestedCommand(command="".join(self.text), opaque=self.opaque)


def _is_control(*, key: str) -> bool:
    return len(key) == 1 and (ord(key) <= _ASCII_CONTROL_MASK or key == "\x7f")


def _typed(*, keys: list[str]) -> NestedCommand:
    line = _TypedLine(text=[])
    for key in keys:
        line.press(key=key)
    return line.nested()


def _hex_keys(*, words: list[str]) -> list[str]:
    keys: list[str] = []
    for word in words:
        try:
            keys.append(chr(int(word, _HEX_BASE)))
        except (ValueError, OverflowError):
            keys.append(_UNKNOWN_KEY)
    return keys


def tmux_command_name(*, token: str) -> str:
    """tmux's command for ``token``: an alias, a name or a unique prefix (GH-2001)."""
    if token in _TMUX_ALIASES:
        return _TMUX_ALIASES[token]
    matches = [name for name in _TMUX_COMMAND_NAMES if token and name.startswith(token)]
    return matches[0] if len(matches) == 1 else token


def _tmux_chunk_keys(*, chunk: list[str], subcommand: int) -> tuple[list[str], list[str]] | None:
    """Keys a ``send-keys`` or ``set-buffer`` chunk types, and its words.

    tmux sends each word as a key name or as literal text, with no blank
    between words, so ``ps ql Enter`` types ``psql``. ``set-buffer`` data
    is counted as typed, since ``paste-buffer`` types it into a pane.
    ``None`` for any other chunk.
    """
    name = tmux_command_name(token=chunk[subcommand])
    if name == _TMUX_SET_BUFFER:
        idx = _skip_options(
            parts=chunk, idx=subcommand + 1, value_options=_TMUX_SET_BUFFER_VALUE_OPTIONS
        )
        return list("".join(chunk[idx:])), chunk[idx:]
    if name != _TMUX_SEND_KEYS:
        return None
    idx = _skip_options(parts=chunk, idx=subcommand + 1, value_options=_TMUX_SEND_VALUE_OPTIONS)
    flags = "".join(token[1:] for token in chunk[subcommand + 1 : idx] if token.startswith("-"))
    words = chunk[idx:]
    return (_hex_keys(words=words) if "H" in flags else words), words


def _tmux_subcommand(*, chunk: list[str], first: bool) -> int | None:
    """Index of the chunk's command, when it is one that runs or types.

    Only the first word after tmux's global options names the command,
    so an option value (`-L ru`) is never read as a prefix (GH-2001).
    """
    idx = (
        _skip_options(parts=chunk, idx=0, value_options=_TMUX_GLOBAL_VALUE_OPTIONS) if first else 0
    )
    wanted = _TMUX_SHELL_COMMANDS | {_TMUX_SEND_KEYS, _TMUX_SET_BUFFER}
    if idx < len(chunk) and tmux_command_name(token=chunk[idx]) in wanted:
        return idx
    return None


def _option_values(*, parts: list[str], options: frozenset[str]) -> str:
    """Every value ``options`` take in ``parts``, spaced or attached, joined."""
    values: list[str] = []
    for idx, token in enumerate(parts):
        if token in options and idx + 1 < len(parts):
            values.append(parts[idx + 1])
        elif len(token) > 2 and token[:2] in options:
            values.append(token[2:])
    return "|".join(values)


def _tmux_pieces(*, parts: list[str]) -> list[tuple[str, list[str]]]:
    """``(target, keys)`` for each chunk that types; the target names the
    server, pane or buffer the keys go to."""
    server = _option_values(parts=parts, options=_TMUX_SERVER_OPTIONS)
    pieces: list[tuple[str, list[str]]] = []
    for position, chunk in enumerate(_tmux_chunks(parts=parts)):
        subcommand = _tmux_subcommand(chunk=chunk, first=position == 0)
        typed = (
            None if subcommand is None else _tmux_chunk_keys(chunk=chunk, subcommand=subcommand)
        )
        if typed is not None:
            target = _option_values(parts=chunk[subcommand:], options=_TMUX_TARGET_OPTIONS)
            pieces.append((f"tmux:{server}:{target}", typed[0]))
    return pieces


def _legacy_tmux_command(*, parts: list[str]) -> str:
    """GH-1998's reading, kept so every command it judged is judged still."""
    subcommand = next(
        (idx for idx, token in enumerate(parts) if token in _TMUX_COMMAND_SUBCOMMANDS), None
    )
    if subcommand is None:
        return ""
    idx = _skip_options(parts=parts, idx=subcommand + 1, value_options=_TMUX_VALUE_OPTIONS)
    words = [word for word in parts[idx:] if word not in _LEGACY_TMUX_KEY_NAMES]
    return " ".join(words)


def _tmux_chunks(*, parts: list[str]) -> list[list[str]]:
    """tmux's argv split into its ``;``-separated commands."""
    chunks: list[list[str]] = [[]]
    for word in parts[1:]:
        if word == _TMUX_SEPARATOR:
            chunks.append([])
        elif word.endswith(_TMUX_SEPARATOR) and not word.endswith(f"\\{_TMUX_SEPARATOR}"):
            chunks[-1].append(word[:-1])
            chunks.append([])
        else:
            chunks[-1].append(word)
    return chunks


def _tmux_commands(*, parts: list[str]) -> list[NestedCommand]:
    commands = [NestedCommand(command=_legacy_tmux_command(parts=parts))]
    for position, chunk in enumerate(_tmux_chunks(parts=parts)):
        subcommand = _tmux_subcommand(chunk=chunk, first=position == 0)
        if position == 0:
            head = ["tmux", *chunk[: len(chunk) if subcommand is None else subcommand]]
            commands.extend(
                NestedCommand(command=command)
                for command in _program_option_commands(
                    parts=head, options=_TMUX_GLOBAL_COMMAND_OPTIONS
                )
            )
        if subcommand is None:
            continue
        typed = _tmux_chunk_keys(chunk=chunk, subcommand=subcommand)
        if typed is not None:
            keys, words = typed
            # The space-joined reading is kept too, so nothing judged
            # before GH-2001 is lost.
            joined = " ".join("\n" if word in _LINE_END_KEYS else word for word in words)
            commands.extend([_typed(keys=keys), NestedCommand(command=joined)])
            continue
        idx = _skip_options(parts=chunk, idx=subcommand + 1, value_options=_TMUX_VALUE_OPTIONS)
        commands.append(NestedCommand(command=" ".join(chunk[idx:])))
    return commands


def _screen_keys(*, payload: str) -> list[str]:
    """``payload`` as the keys ``screen -X stuff`` types (GH-2001).

    screen expands ``\\NNN`` octal, ``\\n``-style and ``^X`` caret escapes
    before typing, so ``'psql\\n'`` runs ``psql``.
    """
    keys: list[str] = []
    position = 0
    for match in _SCREEN_ESCAPE_RE.finditer(payload):
        keys.extend(payload[position : match.start()])
        octal, escaped, caret = match.groups()
        if octal:
            keys.append(chr(int(octal, _OCTAL_BASE)))
        elif escaped is not None:
            keys.append(_SCREEN_BACKSLASH_ESCAPES.get(escaped, escaped))
        else:
            keys.append("\x7f" if caret == "?" else chr(ord(caret.upper()) & _ASCII_CONTROL_MASK))
        position = match.end()
    keys.extend(payload[position:])
    return keys


def _screen_pieces(*, parts: list[str]) -> list[list[str]]:
    """Keys ``screen -X stuff`` types, or ``register`` stores for ``paste``.

    Also read inside ``-X eval '…'``.
    """
    pieces: list[list[str]] = []
    for idx, token in enumerate(parts[1:], start=1):
        if token == _SCREEN_STUFF:
            pieces.append(_screen_keys(payload=" ".join(parts[idx + 1 :])))
        elif token == _SCREEN_REGISTER:
            start = _skip_options(
                parts=parts, idx=idx + 1, value_options=_SCREEN_REGISTER_VALUE_OPTIONS
            )
            pieces.append(_screen_keys(payload=" ".join(parts[start + 1 :])))
        elif token == _SCREEN_EVAL:
            for screen_command in parts[idx + 1 :]:
                pieces.extend(
                    _screen_pieces(parts=["screen", *split_tokens(command=screen_command)])
                )
    return pieces


def _screen_commands(*, parts: list[str]) -> list[NestedCommand]:
    return [_typed(keys=keys) for keys in _screen_pieces(parts=parts)]


def _keystroke_pieces(*, parts: list[str]) -> list[tuple[str, list[str]]]:
    program, stages = _wrapper_walk(parts=parts)
    pieces: list[tuple[str, list[str]]] = []
    for stage in (*stages, program):
        name = stage[0].rsplit("/", 1)[-1] if stage else ""
        if name == "screen":
            session = _option_values(parts=stage, options=_SCREEN_TARGET_OPTIONS)
            pieces.extend((f"screen:{session}", keys) for keys in _screen_pieces(parts=stage))
        elif name == "tmux":
            pieces.extend(_tmux_pieces(parts=stage))
    return pieces


def _is_editing_key(*, key: str) -> bool:
    return key in _ERASE_KEYS or key in _KILL_LINE_KEYS


def _is_literal_key(*, key: str) -> bool:
    return not (
        key in _LINE_END_KEYS
        or key in _BLANK_KEYS
        or _is_editing_key(key=key)
        or key in _NAMED_KEYS
        or _MODIFIED_KEY_RE.match(key)
        or _is_control(key=key)
    )


def typed_streams(*, units: Sequence[Sequence[Sequence[str]]]) -> list[NestedCommand]:
    """The text typed across several keystroke calls, as one line (GH-2001).

    ``units`` holds each unit's segment argvs. ``tmux send-keys ps; tmux
    send-keys ql Enter`` types ``psql`` although neither call does, so
    every piece is replayed in order. The replay cannot be trusted when
    pieces come from more than one unit (their order is not textual), or
    when an erase or kill key may hit another pane or buffer. Then the
    typed letters, erasures ignored, are added as an opaque line, which
    DX004 judges as a multiset. Empty when fewer than two pieces are typed:
    one piece is already judged on its own by :func:`nested_commands`.
    """
    grouped = [
        [piece for argv in segments for piece in _keystroke_pieces(parts=list(argv))]
        for segments in units
    ]
    pieces = [piece for group in grouped for piece in group]
    if len(pieces) < 2:
        return []
    keys = [key for _, piece in pieces for key in piece]
    streams = [_typed(keys=keys)]
    typing_groups = [group for group in grouped if group]
    spans_units = len(typing_groups) > 1
    if spans_units and len(typing_groups) <= _MAX_REORDERED_UNITS:
        streams.extend(
            _typed(keys=[key for group in order for _, piece in group for key in piece])
            for order in permutations(typing_groups)
        )
    targets = {target for target, _ in pieces}
    erases_elsewhere = len(targets) > 1 and any(_is_editing_key(key=key) for key in keys)
    if spans_units or erases_elsewhere:
        letters = "".join(key for key in keys if _is_literal_key(key=key))
        streams.append(NestedCommand(command=letters, opaque=True))
    return streams


def typed_stream(*, segments: Sequence[Sequence[str]]) -> list[NestedCommand]:
    """:func:`typed_streams` for one unit's segments."""
    return typed_streams(units=[segments])


# git runs a configured value as a program: `core.pager`, `core.editor`,
# `alias.x=!cmd`, `credential.helper=!cmd` … Every `-c key=value` value
# and every `git config` word is a candidate, so an unlisted key cannot
# slip through (GH-2001).
_GIT_CONFIG_OPTIONS = frozenset({"-c"})
_GIT_CONFIG_SUBCOMMAND = "config"
_GIT_SHELL_ALIAS = "!"


def _git_commands(*, parts: list[str]) -> list[str]:
    values = [
        value.partition("=")[2]
        for value in _program_option_commands(parts=parts, options=_GIT_CONFIG_OPTIONS)
        if "=" in value
    ]
    if _GIT_CONFIG_SUBCOMMAND in parts[1:]:
        start = parts.index(_GIT_CONFIG_SUBCOMMAND, 1) + 1
        values.extend(word for word in parts[start:] if not word.startswith("-"))
    return [value.lstrip(_GIT_SHELL_ALIAS) for value in values]


def _parallel_commands(*, parts: list[str]) -> list[str]:
    idx = _skip_options(parts=parts, idx=1, value_options=_PARALLEL_VALUE_OPTIONS)
    rest = parts[idx:]
    end = next((i for i, word in enumerate(rest) if word in _PARALLEL_SEPARATORS), len(rest))
    if end:
        return [shlex.join(rest[:end])]
    # No command template: each argument is itself a command line.
    return [word for word in rest[end:] if word not in _PARALLEL_SEPARATORS]


def _find_exec_commands(*, parts: list[str]) -> list[str]:
    commands: list[str] = []
    idx = 1
    while idx < len(parts):
        if parts[idx] not in _FIND_EXEC_ACTIONS:
            idx += 1
            continue
        end = idx + 1
        while end < len(parts) and parts[end] not in _FIND_EXEC_TERMINATORS:
            end += 1
        if end > idx + 1:
            commands.append(shlex.join(parts[idx + 1 : end]))
        idx = end + 1
    return commands


def nested_commands(*, parts: list[str]) -> list[NestedCommand]:
    """Commands a runner in ``parts`` executes on the caller's behalf (GH-1774).

    ``parts`` is one segment's argv after :func:`strip_command_wrappers`.
    ``ssh host 'dropdb x'`` yields ``dropdb x`` (remote); ``su app -c
    'python -c x'`` yields ``python -c x``. A container CLI yields every
    candidate suffix. Empty for anything that runs no nested command.
    """
    if not parts:
        return []
    name = parts[0].rsplit("/", 1)[-1]
    if name in _SU_RUNNERS:
        commands = [_su_command(parts=parts)]
    elif name == "find":
        commands = _find_exec_commands(parts=parts)
    elif name == "op":
        commands = [_op_run_command(parts=parts)]
    elif name == "eval":
        commands = [" ".join(parts[1:])]
    elif name == "watch":
        commands = [_watch_command(parts=parts)]
    elif name == "flock":
        commands = [_flock_command(parts=parts)]
    elif name in _PROGRAM_OPTIONS:
        commands = _program_option_commands(parts=parts, options=_PROGRAM_OPTIONS[name])
    elif name == "gdb":
        commands = [_gdb_command(parts=parts)]
    elif name == "tmux":
        return _distinct(commands=_tmux_commands(parts=parts))
    elif name == "screen":
        return _distinct(commands=_screen_commands(parts=parts))
    elif name == "git":
        commands = _git_commands(parts=parts)
    elif name == "parallel":
        commands = _parallel_commands(parts=parts)
    elif name == "ssh":
        return [NestedCommand(command=_ssh_command(parts=parts), remote=True)]
    elif name in _CONTAINER_CLIS:
        return [
            NestedCommand(command=command, remote=True)
            for command in _container_commands(parts=parts)
        ]
    else:
        return []
    return [NestedCommand(command=command) for command in commands if command]


def _distinct(*, commands: list[NestedCommand]) -> list[NestedCommand]:
    """``commands`` trimmed and deduplicated; a duplicate keeps any opacity."""
    merged: dict[str, NestedCommand] = {}
    for nested in commands:
        text = nested.command.strip()
        if not text:
            continue
        opaque = nested.opaque or (text in merged and merged[text].opaque)
        merged[text] = NestedCommand(command=text, remote=nested.remote, opaque=opaque)
    return list(merged.values())


def runner_commands(*, parts: list[str]) -> list[NestedCommand]:
    """:func:`nested_commands` for one segment's raw argv, wrappers included.

    ``screen`` is both a wrapper (``screen psql``) and a keystroke runner
    (``screen -X stuff 'psql\\n'``), so each wrapper stripped on the way
    to the program is asked for its nested commands too (GH-2001).
    """
    program, stages = _wrapper_walk(parts=parts)
    return [nested for stage in (*stages, program) for nested in nested_commands(parts=stage)]


def _runner_bodies(*, unit: str) -> list[NestedCommand]:
    # Cheap word probe first: the hook runs on every Bash call under a CI
    # latency benchmark, and most commands name no runner at all.
    if not _RUNNER_PROBE.found_in(command=unit):
        return []
    try:
        segments = command_segments(command=unit)
    except UntokenizableCommandError:
        return []
    nested = [
        nested for segment in segments for nested in runner_commands(parts=list(segment.argv))
    ]
    return [*nested, *typed_stream(segments=[segment.argv for segment in segments])]
