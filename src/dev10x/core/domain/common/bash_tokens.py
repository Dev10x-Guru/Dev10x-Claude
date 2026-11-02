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
from dataclasses import dataclass
from functools import lru_cache

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


_COMMAND_WRAPPERS: dict[str, _Wrapper] = {
    "env": _Wrapper(value_options=frozenset({"-u", "--unset", "-C", "--chdir"})),
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


# A redirect word: optional fd number or `&`, then `<` or `>`. A bare
# operator has its target in the next word; an attached one does not.
_REDIRECT_TOKEN_RE = re.compile(r"^(?:\d+|&)?[<>]")
_BARE_REDIRECT_RE = re.compile(r"(?:\d+|&)?(?:[<>]{1,3}|>[&|]|<&)")


def _bundle_takes_next_value(*, token: str, value_options: frozenset[str]) -> bool:
    """True when a short-option bundle ends on a value option.

    ``sudo -iu postgres dropdb`` bundles ``-i`` with ``-u``; the bundle's
    last letter takes the next token. A value letter mid-bundle has its
    value attached (``-u5``), so nothing more is consumed.
    """
    if token.startswith("--") or len(token) < 3:
        return False
    letters = token[1:]
    for position, letter in enumerate(letters):
        if f"-{letter}" in value_options:
            return position == len(letters) - 1
    return False


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


def _skip_wrapper_options(*, parts: list[str], idx: int, wrapper: _Wrapper) -> int:
    idx = _skip_options(parts=parts, idx=idx, value_options=wrapper.value_options)
    return min(idx + wrapper.positionals, len(parts))


def strip_command_wrappers(*, parts: list[str]) -> list[str]:
    """``parts`` from the program actually run, past env, wrappers and runners.

    ``FOO=1 timeout 30 nice -n 5 python -c …`` yields ``["python", "-c", …]``.
    Guards that judge ``parts[0]`` otherwise see ``timeout`` and abstain,
    which is the evasion GH-1630's review found for DX003 and DX004.
    ``sudo``, ``doas`` and ``xargs`` unwrap the same way (GH-1774), so
    ``sudo -u app python -c …`` is judged as the ``python`` call it is.
    A redirect may precede the program too: ``>/dev/null python -c …``.
    """
    idx = 0
    while idx < len(parts):
        token = parts[idx]
        if ANY_CASE_ENV_VAR_RE.match(token):
            idx += 1
            continue
        if _REDIRECT_TOKEN_RE.match(token):
            # A bare operator (`>`, `2>`) takes the next word as its target.
            idx += 2 if _BARE_REDIRECT_RE.fullmatch(token) else 1
            continue
        wrapper = _COMMAND_WRAPPERS.get(token.rsplit("/", 1)[-1])
        if wrapper is None:
            break
        idx = _skip_wrapper_options(parts=parts, idx=idx + 1, wrapper=wrapper)
    return parts[idx:]


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
    units = [command]
    seen = {command}
    pending = [command]
    while pending:
        unit = pending.pop()
        bodies = [
            *substitution_bodies(unit, include_backticks=True),
            *(
                nested.command
                for nested in _runner_bodies(unit=unit)
                if include_remote or not nested.remote
            ),
        ]
        for body in bodies:
            if body.strip() and body not in seen:
                seen.add(body)
                units.append(body)
                pending.append(body)
    return tuple(units)


_PIPE_OPERATORS = frozenset({"|", "|&"})
# Characters that start an operator ending one command (GH-1773). An
# unquoted newline ends a command the way `;` does.
_OPERATOR_CHARS = ";&|()\n"
_TWO_CHAR_OPERATORS = frozenset({";;", "&&", "||", "|&"})
# A set, not a string: after a quoted part `last_unquoted` is "", and
# `"" in "<>"` is True, which glued a background `&` onto `'a'&`.
_REDIRECT_CHARS = frozenset("<>")
_BLANKS = " \t\r"
_DOUBLE_QUOTE_ESCAPES = '$`"\\\n'

# Reserved words that may open a segment without being the program it
# runs: `if dropdb x; then …` and `do ruff check $f` both run the word
# after the keyword. Process wrappers (`time`, `exec`, `command`) are not
# here; `strip_command_wrappers` owns them, options and all.
SHELL_KEYWORDS = frozenset({"!", "{", "}", "if", "then", "else", "elif", "while", "until", "do"})


class UntokenizableCommandError(ValueError):
    """Raised when a command cannot be split into segments.

    Callers decide explicitly whether that fails closed (a safety guard
    falls back to :func:`command_position_re`) or abstains (a friction
    rule has no invocation to anchor on).
    """


@dataclass(frozen=True)
class CommandSegment:
    """One simple command: its argv and the operator that opened it."""

    argv: tuple[str, ...]
    opener: str = ""

    @property
    def is_piped(self) -> bool:
        """True when the segment reads the previous segment's output."""
        return self.opener in _PIPE_OPERATORS


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    is_operator: bool = False


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
        while self.index < len(self.source):
            char = self.source[self.index]
            if char in _BLANKS:
                self.index += 1
            elif char == "\\" and self.source.startswith("\\\n", self.index):
                self.index += 2
            elif char == "#":
                self._skip_comment()
            elif char in _OPERATOR_CHARS and not self._is_redirect_ampersand():
                operator = self._operator()
                tokens.append(_Token(text=operator, is_operator=True))
                if operator == "\n" and heredocs:
                    self._skip_heredoc_bodies(heredocs=heredocs)
                    heredocs = []
            else:
                start = self.index
                word = self._word()
                tokens.append(_Token(text=word))
                opens_heredoc = self.source.startswith("<<", start)
                if awaiting_delimiter is not None:
                    heredocs.append((word, awaiting_delimiter))
                    awaiting_delimiter = None
                elif opens_heredoc and not self.source.startswith("<<<", start):
                    strip_tabs = word.startswith("<<-")
                    delimiter = word[3:] if strip_tabs else word[2:]
                    if delimiter:
                        heredocs.append((delimiter, strip_tabs))
                    else:
                        awaiting_delimiter = strip_tabs
        return tokens

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

    def _word(self) -> str:
        chars: list[str] = []
        last_unquoted = ""
        while self.index < len(self.source):
            char = self.source[self.index]
            if char in _BLANKS:
                break
            if char in _OPERATOR_CHARS:
                glued = (
                    char == "&"
                    and (last_unquoted in _REDIRECT_CHARS or self._is_redirect_ampersand())
                ) or (char == "|" and last_unquoted == ">")
                if not glued:
                    break
            if char == "\\":
                if self.source.startswith("\\\n", self.index):
                    self.index += 2
                    continue
                chars.append(self.source[self.index + 1 : self.index + 2])
                self.index += 2
                last_unquoted = ""
            elif char == "'":
                chars.append(self._single_quoted())
                last_unquoted = ""
            elif char == '"':
                chars.append(self._double_quoted())
                last_unquoted = ""
            else:
                chars.append(char)
                self.index += 1
                last_unquoted = char
        return "".join(chars)

    def _single_quoted(self) -> str:
        end = self.source.find("'", self.index + 1)
        if end == -1:
            raise UntokenizableCommandError("unterminated single quote")
        text = self.source[self.index + 1 : end]
        self.index = end + 1
        return text

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
    Substitution bodies are not unwrapped here; :func:`command_units`
    hands each one over as its own command.

    Raises :class:`UntokenizableCommandError` on an unbalanced quote.
    Skipping such input silently was the evasion this function replaces,
    so every caller must choose its fallback.
    """
    segments: list[CommandSegment] = []
    argv: list[str] = []
    opener = ""
    for token in _Scanner(source=command).tokens():
        if token.is_operator:
            # A newline ends a command the way `;` does.
            operator = ";" if token.text == "\n" else token.text
            if argv:
                segments.append(CommandSegment(argv=tuple(argv), opener=opener))
                argv = []
                opener = operator
            elif opener not in _PIPE_OPERATORS:
                opener = operator
            continue
        if not argv and token.text in SHELL_KEYWORDS:
            continue
        argv.append(token.text)
    if argv:
        segments.append(CommandSegment(argv=tuple(argv), opener=opener))
    return tuple(segments)


# A command boundary: start of input or a shell operator, then any env
# assignments and process wrappers or runners with their option tokens.
COMMAND_BOUNDARY = r"(?:^|[|;&(\n{])\s*"
ENV_ASSIGNMENTS = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
_WRAPPER_NAMES = "|".join(sorted(_COMMAND_WRAPPERS))
WRAPPER_PREFIX = rf"(?:(?:[\w./~-]*/)?(?:{_WRAPPER_NAMES})\s+(?:(?:-\S*|\d\S*)\s+)*)*"


def command_position_re(*, program: str) -> re.Pattern[str]:
    """Match ``program`` in command position, not as an argument (GH-971).

    ``program`` is a regex fragment. The match must follow a command
    boundary, optionally behind env assignments, wrappers or runners
    (``sudo``, ``timeout 30``) and a directory prefix (``/bin/sh``). A
    bare word search would also match a filename argument such as
    ``bin/x.sh``.

    This is the fail-closed fallback for :class:`UntokenizableCommandError`:
    it over-matches by design, and a wrapper option that takes a word
    value (``sudo -u app``) is past what it can see.
    """
    return re.compile(
        COMMAND_BOUNDARY
        + ENV_ASSIGNMENTS
        + WRAPPER_PREFIX
        + r"(?:[\w./~-]*/)?(?:"
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
_RUNNER_WORD_RE = re.compile(
    r"\b(?:" + "|".join(sorted({"ssh", "op", "find", *_CONTAINER_CLIS, *_SU_RUNNERS})) + r")\b"
)
_SHELL_QUOTING = str.maketrans("", "", "\"'\\")


def without_shell_quoting(*, text: str) -> str:
    """``text`` minus quote and escape characters, for word probes.

    ``s''sh`` and ``b\\q`` run ``ssh`` and ``bq`` while the raw text names
    neither, so a probe that gates a check must search this instead.
    """
    return text.translate(_SHELL_QUOTING)


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
        if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:
            # `-lc 'cmd'` bundles `-c` last; `-c'cmd'` attaches its value.
            attached = token[token.index("c", 1) + 1 :]
            return attached or following
    return ""


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


def _runner_bodies(*, unit: str) -> list[NestedCommand]:
    # Cheap word probe first: the hook runs on every Bash call under a CI
    # latency benchmark, and most commands name no runner at all.
    if not _RUNNER_WORD_RE.search(without_shell_quoting(text=unit)):
        return []
    try:
        segments = command_segments(command=unit)
    except UntokenizableCommandError:
        return []
    return [
        nested
        for segment in segments
        for nested in nested_commands(parts=strip_command_wrappers(parts=list(segment.argv)))
    ]
