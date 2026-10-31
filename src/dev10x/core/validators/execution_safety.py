"""Validator: execution safety patterns.

Consolidates validate-bash-security.py (Bash branch) and
block-python3-inline.py.

Blocks:
  1. Shell-based file writes (cat >, echo >, printf >)
  2. In-place file editors (sed -i, perl -i, gawk -i inplace, dd of=)
  3. Interpreter inline code (python -c, bash/sh/zsh -c)
  4. Interpreters reading a script via stdin (heredoc/here-string,
     bare `-`, shell `-s`, or a pipe feeding the interpreter) — GH-687
  5. Interpreters running untrusted absolute script paths
     (python/bash/sh/zsh <untrusted-abs-path>)

"python" means every interpreter name (``python``, ``python3``,
``python3.12``, ``/usr/bin/python3``) and every launcher that hands its
argv to one (``uv run``, ``uv --project X run``, ``uvx``, ``poetry run``,
``pipenv run``) — GH-1630. Matching only the literal ``python3`` token
let ``uv --project apps/api run python -c "…"`` straight through.

The interpreter guard (GH-469) treats bash/sh/zsh as siblings of
python3: the `bash <verb> *` catch-all is the higher-severity footgun
(arbitrary shell, total rule bypass), so it must be hook-enforced here
rather than left to an unreliable permission deny-rule.

The stdin channels (GH-687) are the inverse of the `-c` guard: the real
payload runs inside the interpreter subprocess, invisible to every other
PreToolUse validator (skill-redirect, sql-safety, sensitivity). The `-c`
block (GH-469) closed the flag channel; this closes the stdin channels.
node/ruby/perl are intentionally out of scope here — they never had the
`-c`/`-e` inline guard, so closing only their stdin channel would be
incoherent; tracked as separate follow-up.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.bash_tokens import strip_command_wrappers, substitution_bodies
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

# Verbs that write a file when paired with a redirect. Judged in
# COMMAND position only (GH-1087) — see `_check_shell_writes`.
SHELL_WRITE_CMDS = frozenset({"cat", "echo", "printf"})

# Fallback matcher for a segment `shlex` cannot parse. Word-occurrence
# based, so it over-matches; it runs only on the fail-closed path where
# over-matching is the safe direction.
SHELL_WRITE_RE = re.compile(
    r"\bcat\b\s*(>|<<|>\s*\S)"
    r"|\becho\b\s+.*\s*(>|>>)\s*\S"
    r"|\bprintf\b.*\s*(>|>>)\s*\S"
    r"|\$\(printf\b"
)

# Matches dd of= writes to real files; excludes /dev/null, /dev/stdout, /dev/stderr
_DD_OF_RE = re.compile(r"\bof=(?!/dev/(null|stdout|stderr)\b)\S")

APPROVED_ABS_PREFIXES = (
    f"{ClaudeDir.tools_dir()}/",
    f"{ClaudeDir.skills_dir()}/",
    f"{ClaudeDir.hooks_dir()}/",
)

SHELL_WRITE_MSG = (
    "Use the Write/Edit tool instead of cat/echo/printf redirects.\n"
    "For multi-line commit messages: get a path with"
    ' mcp__plugin_dev10x_cli__mktmp(namespace="git", prefix="commit-msg",'
    ' ext=".txt"),'
    " Write content to the returned path, then git commit -F <path>"
    " (GH-1318)"
)

INPLACE_EDIT_MSG = (
    "Use the Write/Edit tool instead of in-place stream editors"
    " (sed -i, perl -i, gawk -i inplace, dd of=).\n"
    "Read-only forms are fine: sed -n, sed/awk writing to stdout,"
    " perl -ne/-pe without -i."
)

PYTHON3_INLINE_MSG = """\
\U0001f6ab  python inline/stdin/untrusted script blocked.

This covers python, python3, python3.N and launchers such as
`uv run python`, `uvx python`, `poetry run python` and `pipenv run python`.
`python script.py`, `python -m pytest` and `uv run pytest` stay allowed.

Use the Write tool to create a self-contained uv script instead:

  Step 1 \u2014 Get a path from mcp__plugin_dev10x_cli__mktmp
           (or pick /tmp/Dev10x/<name>.py) and Write the script there:

    #!/usr/bin/env -S uv run --script
    # /// script
    # requires-python = ">=3.11"
    # dependencies = []  # add packages here if needed, e.g. ["requests"]
    # ///

    # your code here

  Step 2 \u2014 Run it:

    uv run --script /tmp/Dev10x/<name>.py

Benefits:
  - Reproducible: deps declared inline (PEP 723), no pip install needed
  - Auditable: Write tool diffs show exactly what runs
  - Permitted: uv run:* is pre-approved; /tmp/Dev10x/ is writable

If the script needs no third-party deps, the # /// block can be omitted."""

SHELL_INTERPRETERS = ("bash", "sh", "zsh")


def _heredoc_into_re(program: str) -> re.Pattern[str]:
    """Match a heredoc/here-string feeding ``program`` via stdin (GH-687).

    ``program`` is a regex fragment naming the interpreter (and, for
    python, the launchers that reach it — GH-1630). It must appear at a
    command boundary (start, pipe, ``;``, ``&``, ``(``, or newline),
    optionally preceded by ``VAR=value`` env prefixes, and be followed on
    the same line by ``<<`` (heredoc) or ``<<<`` (here-string). Matched
    on the whole command so a ``|`` inside the heredoc body never
    confuses pipeline splitting.

    Substitutions need no boundary character here (GH-986). Each body is
    passed in as its own unit by :func:`_command_units`, stripped of its
    ``$(``/backtick wrapper, so the interpreter lands at ``^``.
    """
    return re.compile(
        r"(?:^|[|;&(\n])\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*" + program + r"\b[^\n]*?<<"
    )


def _command_position_re(program: str) -> re.Pattern[str]:
    """Match ``interpreter`` in COMMAND position, not as an argument (GH-971).

    Guards the fail-closed path only. A bare ``\\b<interpreter>\\b`` search
    also matches a *filename* argument — ``bin/tachyon-env.sh`` ends on a
    word-boundaried ``sh`` — so a read-only ``grep -E 'a|b' bin/x.sh`` was
    blocked as script execution: the alternation ``|`` splits the pipeline
    mid-quote, ``shlex`` then fails on the unbalanced quote, and the
    fail-closed fallback matched the file extension.

    Command position means: start of string or after a ``|``/``;``/``&``/
    ``(``/newline separator, optionally preceded by ``VAR=value`` env
    prefixes and optionally carrying a directory prefix (``/bin/sh``).

    Note the scope: this pattern guards the ``shlex``-raised branch only.
    An interpreter inside a substitution is caught by checking each body
    as its own unit (:func:`_command_units`), not here.
    """
    return re.compile(
        r"(?:^|[|;&(\n])\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
        r"(?:[\w./~-]*/)?" + program + r"\b"
    )


def _command_units(command: str) -> tuple[str, ...]:
    """``command`` plus every command it nests in a substitution (GH-986).

    A substitution runs its body as its own command, so each body is a
    unit the interpreter guard must judge on its own terms.

    Flattened ONCE per check rather than re-derived per interpreter. The
    guard runs on every Bash tool call under a 2x-baseline CI benchmark,
    and `_check_one_interpreter`'s substring guard admits ``sh`` for any
    command merely mentioning ``bash``, ``zsh``, or a ``.sh`` filename —
    so a per-interpreter scan would repeat this work several times over
    on very ordinary commands.

    The sweep is breadth-first because ``substitution_bodies`` returns
    only the outermost bodies: re-scanning each one is what reaches a
    nested ``$(python3 -c "$(echo x)")``.
    """
    units = [command]
    pending = [command]
    while pending:
        for body in substitution_bodies(pending.pop(), include_backticks=True):
            if body.strip():
                units.append(body)
                pending.append(body)
    return tuple(units)


_PYTHON_NAME_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?(?:@[\w.]+)?")

# A launcher that hands its remaining argv to an interpreter, mapped to
# the subcommand paths that may precede the interpreter name: `uv run`,
# `uv tool run` (the long form of `uvx`), `poetry run` — or an empty path
# when the launcher takes it directly (`uvx python`). GH-1630.
_PYTHON_LAUNCHERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "uv": (("run",), ("tool", "run")),
    "poetry": (("run",),),
    "pipenv": (("run",),),
    "uvx": ((),),
}
_LAUNCHER_SUBCOMMAND_WORDS = frozenset(
    word for paths in _PYTHON_LAUNCHERS.values() for path in paths for word in path
)

# Launcher options known to consume the next token, so the value is never
# mistaken for the subcommand or the interpreter (`uv --project python run
# python -c …` must still find the second `python`). `--opt=value` needs no
# entry; it is one token. An option missing from this list is treated as
# value-taking unless the next token is itself an option, a subcommand
# word, or a python name — the fail-closed reading (`uv --color always run
# python -c …` must not slip through on an unlisted flag).
_LAUNCHER_VALUE_OPTIONS = frozenset(
    {
        "--project",
        "--directory",
        "-C",
        "--with",
        "-w",
        "--with-editable",
        "--with-requirements",
        "--extra",
        "--group",
        "--only-group",
        "--package",
        "--python",
        "-p",
        "--index",
        "--default-index",
        "--index-url",
        "--extra-index-url",
        "--find-links",
        "-f",
        "--env-file",
        "--from",
        "--cache-dir",
        "--config-file",
    }
)

# Regex twin of `_python_argv` for the two whole-command matchers
# (heredoc, fail-closed). Interpreter name with an optional launcher in
# front; the launcher's own options ride in the lazy middle span.
_PYTHON_PROGRAM = (
    r"(?:(?:(?:uv\s(?:[^\n|;&]*?\s)?(?:tool\s+)?run|(?:poetry|pipenv)\s(?:[^\n|;&]*?\s)?run|uvx)"
    r"\s(?:[^\n|;&]*?\s)?))?"
    r"(?:[\w./~-]*/)?python(?:\d+(?:\.\d+)*)?(?:@[\w.]+)?"
)


def _is_python_name(token: str) -> bool:
    return _PYTHON_NAME_RE.fullmatch(Path(token).name) is not None


def _is_launcher_anchor(token: str) -> bool:
    return token.startswith("-") or token in _LAUNCHER_SUBCOMMAND_WORDS or _is_python_name(token)


def _skip_launcher_options(tokens: list[str]) -> list[str]:
    """``tokens`` from the first positional on, with launcher options dropped."""
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token == "--":
            return tokens[idx + 1 :]
        if not token.startswith("-"):
            return tokens[idx:]
        idx += 1
        if "=" in token or idx >= len(tokens):
            continue
        if token in _LAUNCHER_VALUE_OPTIONS or not _is_launcher_anchor(tokens[idx]):
            idx += 1
    return []


def _after_subcommands(tokens: list[str], *, path: tuple[str, ...]) -> list[str] | None:
    rest = _skip_launcher_options(tokens)
    for word in path:
        if not rest or rest[0] != word:
            return None
        rest = _skip_launcher_options(rest[1:])
    return rest


def _python_argv(parts: list[str]) -> list[str] | None:
    """The interpreter's own argv when ``parts`` runs python, else ``None``.

    Unwraps one launcher layer (GH-1630), so ``uv --project X run python
    -c …`` yields ``["-c", …]`` exactly like ``python -c …`` does. A
    launcher running anything other than python (``uv run pytest``)
    yields ``None`` — it is not this guard's business.
    """
    head = Path(parts[0]).name
    if _is_python_name(head):
        return parts[1:]
    for path in _PYTHON_LAUNCHERS.get(head, ()):
        rest = _after_subcommands(parts[1:], path=path)
        if rest and _is_python_name(rest[0]):
            return rest[1:]
    return None


def _exact_argv(parts: list[str], *, name: str) -> list[str] | None:
    return parts[1:] if parts[0] == name else None


class _Run(StrEnum):
    """What an interpreter invocation will execute.

    ``SCRIPT`` pairs with the script path, or ``None`` for a bare
    interpreter (a REPL, or a program piped in from upstream).
    """

    INLINE = "inline"  # code from argv or stdin — never inspectable
    MODULE = "module"
    SCRIPT = "script"


# Python short options whose value follows (attached or as the next token).
_PYTHON_VALUE_LETTERS = frozenset({"W", "X"})


def _python_short_cluster(*, letters: str) -> tuple[_Run | None, bool]:
    """``(run, takes_next_token)`` for one short-option cluster."""
    for pos, letter in enumerate(letters):
        if letter == "c":
            return _Run.INLINE, False
        if letter == "m":
            return _Run.MODULE, False
        if letter in _PYTHON_VALUE_LETTERS:
            return None, pos == len(letters) - 1
    return None, False


def _python_target(argv: list[str]) -> tuple[_Run, str | None]:
    """Read python's own options the way CPython does, up to the script.

    ``-c`` counts inside a cluster (``-Ic``), ``-m`` only when it comes
    first, and anything after the script or module name belongs to it —
    so ``python tool.py -c conf.yaml`` is a script run, not inline code.
    """
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        idx += 1
        if token == "--":
            break
        if token == "-":
            return _Run.INLINE, None
        if token.startswith("--"):
            continue
        if not token.startswith("-"):
            return _Run.SCRIPT, token
        run, takes_next = _python_short_cluster(letters=token[1:])
        if run is not None:
            return run, None
        idx += takes_next
    script = argv[idx] if idx < len(argv) else None
    if script == "-":
        return _Run.INLINE, None
    return _Run.SCRIPT, script


def _shell_target(argv: list[str]) -> tuple[_Run, str | None]:
    # `-c` anywhere, a bare `-`, or `-s` in any short cluster (`-se`)
    # delivers the program inline or over stdin.
    if any(a.startswith("-c") for a in argv) or "-" in argv:
        return _Run.INLINE, None
    if any(a.startswith("-") and not a.startswith("--") and "s" in a[1:] for a in argv):
        return _Run.INLINE, None
    return _Run.SCRIPT, next((a for a in argv if not a.startswith("-")), None)


@dataclass(frozen=True)
class _Interpreter:
    """How to recognise one guarded interpreter in a command.

    ``token`` is a cheap substring pre-filter; ``argv_of`` returns the
    interpreter's own argv from a tokenized segment, or ``None`` when the
    segment runs something else; ``target`` reads that argv into what
    will actually execute.
    """

    token: str
    heredoc: re.Pattern[str]
    command_position: re.Pattern[str]
    argv_of: Callable[[list[str]], list[str] | None]
    target: Callable[[list[str]], tuple[_Run, str | None]]


_PYTHON = _Interpreter(
    token="python",
    heredoc=_heredoc_into_re(_PYTHON_PROGRAM),
    command_position=_command_position_re(_PYTHON_PROGRAM),
    argv_of=_python_argv,
    target=_python_target,
)
_SHELLS = tuple(
    _Interpreter(
        token=name,
        heredoc=_heredoc_into_re(re.escape(name)),
        command_position=_command_position_re(re.escape(name)),
        argv_of=partial(_exact_argv, name=name),
        target=_shell_target,
    )
    for name in SHELL_INTERPRETERS
)

# Shell interpreters may additionally run scripts staged under the Dev10x
# temp dir (GH-370 pre-approves /tmp/Dev10x/ execution); python3 keeps the
# narrower APPROVED_ABS_PREFIXES set.
SHELL_APPROVED_ABS_PREFIXES = (*APPROVED_ABS_PREFIXES, "/tmp/Dev10x/")

SHELL_INTERP_MSG = """\
\U0001f6ab  shell inline/stdin/untrusted script execution blocked.

`bash`/`sh`/`zsh` running inline code (`-c`), a script via stdin
(heredoc, `-s`, `-`, or a pipe), or an untrusted absolute script path
bypasses every PreToolUse guardrail. Use one of:

  - Inline logic — Write a self-contained uv script to
    /tmp/Dev10x/<name>.py via the Write tool, then `uv run --script` it
    (auditable diff, declared deps, no rule bypass).
  - An existing script — run it directly via its shebang
    (./script.sh) instead of `bash script.sh`.
  - A staged script — place it under an approved dir and run it
    there: ~/.claude/{tools,skills,hooks}/ or /tmp/Dev10x/.

Relative paths (e.g. `bash ./build.sh`) and approved-dir absolute paths
are allowed; only inline `-c` and untrusted absolute paths are blocked."""


def _is_approved_path(path: str, prefixes: tuple[str, ...] = APPROVED_ABS_PREFIXES) -> bool:
    expanded = os.path.expanduser(path)
    return any(expanded.startswith(p) or path.startswith(p) for p in prefixes)


def _has_inplace_flag(*, argv: list[str], cmd: str) -> bool:
    """Return True if the argument list indicates an in-place edit operation.

    Handles:
    - sed: any short-flag cluster that contains 'i' (e.g. -i, -ni, -in, -in.bak)
    - perl: any short-flag cluster that contains 'i' (e.g. -i, -pi, -pi.bak)
    - gawk/awk: '-i' followed by 'inplace' as a separate token
    - dd: delegated to caller via _DD_OF_RE
    """
    if cmd in ("sed", "perl"):
        for arg in argv:
            # Only inspect short-flag clusters (start with '-' but not '--')
            if arg.startswith("-") and not arg.startswith("--"):
                # Strip the leading '-' and any optional suffix after the flags
                # e.g. '-i.bak' \u2192 flag letters = 'i', suffix = '.bak'
                # e.g. '-ni' \u2192 flag letters = 'ni'
                flag_body = arg[1:]
                # Collect contiguous alpha chars as the flag cluster
                flag_letters = ""
                for ch in flag_body:
                    if ch.isalpha():
                        flag_letters += ch
                    else:
                        break
                if "i" in flag_letters:
                    return True
        return False

    if cmd in ("gawk", "awk"):
        # gawk -i inplace: '-i' must be immediately followed by 'inplace'
        for idx, arg in enumerate(argv):
            if arg in ("-i", "--include") and idx + 1 < len(argv):
                if argv[idx + 1] == "inplace":
                    return True
        return False

    return False


@dataclass
class ExecutionSafetyValidator(ValidatorBase):
    name: ClassVar[str] = "execution-safety"
    rule_id: ClassVar[str] = "DX003"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        return True

    def validate(self, inp: HookInput) -> HookResult | None:
        # Check shell writes first; if flagged, report immediately.
        result = self._check_shell_writes(command=inp.command)
        if result:
            return result
        # Check in-place editors before python3 so mis-keyed sed/perl is caught
        # early, consistent with first-block-wins ordering.
        result = self._check_inplace_edit(command=inp.command)
        if result:
            return result
        return self._check_interpreter(command=inp.command, cwd=inp.cwd)

    def _check_shell_writes(self, *, command: str) -> HookResult | None:
        """Block `cat`/`echo`/`printf` writing a file through a redirect.

        Judged in COMMAND position, per pipeline segment, the same way
        `_check_inplace_edit` and `_check_one_interpreter` judge theirs.
        A word-occurrence match cannot tell a command from an argument
        or a flag: `find … -printf '%p\\n' 2>/dev/null` was blocked as a
        shell write because the `2>` supplied the redirect and
        `\\bprintf\\b` matched find's `-printf` primary — a
        format-string action writing to stdout, sibling of the `-print`
        beside it. The steer was doubly wrong, since Write/Edit cannot
        enumerate files (GH-1087). `ls cat > out.txt` was the same bug
        wearing an argument instead of a flag.

        Substitution bodies are judged as their own units, so
        `$(printf x > /tmp/f)` is still caught.
        """
        for unit in _command_units(command):
            for segment in unit.split("|"):
                try:
                    parts = shlex.split(segment)
                except ValueError:
                    # Fail closed (mirroring the interpreter guard): an
                    # unparseable segment is judged by the looser regex,
                    # where over-matching is the safe direction.
                    if SHELL_WRITE_RE.search(segment):
                        return HookResult(message=SHELL_WRITE_MSG)
                    continue

                parts = strip_command_wrappers(parts=parts)
                if not parts:
                    continue
                verb = Path(parts[0]).name
                if verb not in SHELL_WRITE_CMDS:
                    continue

                # A heredoc counts only for `cat` — `cat <<EOF` is itself a
                # write shape. A heredoc after `echo` belongs to whatever
                # the substitution runs (`echo $(python3 <<PY …)`), which
                # the interpreter guard judges on its own terms.
                if any(">" in arg for arg in parts[1:]) or (
                    verb == "cat" and any(arg.startswith("<<") for arg in parts[1:])
                ):
                    return HookResult(message=SHELL_WRITE_MSG)

        return None

    def _check_inplace_edit(self, *, command: str) -> HookResult | None:
        """Detect in-place file editors and steer to Write/Edit tool.

        Scans each pipeline segment so `cat x | sed -i ...` is caught.
        Returns a HookResult on the first flagged segment, None otherwise.
        """
        _INPLACE_CMDS = frozenset({"sed", "perl", "gawk", "awk", "dd"})

        for segment in command.split("|"):
            segment = segment.strip()
            try:
                parts = shlex.split(segment)
            except ValueError:
                return None

            parts = strip_command_wrappers(parts=parts)
            if not parts:
                continue

            cmd = parts[0]
            if cmd not in _INPLACE_CMDS:
                continue

            argv = parts[1:]

            if cmd == "dd":
                if _DD_OF_RE.search(segment):
                    return HookResult(message=INPLACE_EDIT_MSG)
                continue

            if _has_inplace_flag(argv=argv, cmd=cmd):
                return HookResult(message=INPLACE_EDIT_MSG)

        return None

    def _check_interpreter(self, *, command: str, cwd: str = "") -> HookResult | None:
        """Block inline code and untrusted absolute script paths for
        python3 and the shell interpreters (bash/sh/zsh).

        python3 keeps its `-m` carve-out and the narrow approved-prefix
        set; the shell interpreters additionally allow /tmp/Dev10x/.
        An absolute script inside ``cwd`` is trusted like its relative
        spelling (GH-1683). First match wins (python3 checked before the shells), so the
        interpreter loop stays outermost and each one sweeps every unit
        before the next interpreter is tried.
        """
        units = _command_units(command)

        for unit in units:
            result = self._check_one_interpreter(
                command=unit,
                interpreter=_PYTHON,
                approved=APPROVED_ABS_PREFIXES,
                message=PYTHON3_INLINE_MSG,
                cwd=cwd,
            )
            if result:
                return result

        for interpreter in _SHELLS:
            for unit in units:
                result = self._check_one_interpreter(
                    command=unit,
                    interpreter=interpreter,
                    approved=SHELL_APPROVED_ABS_PREFIXES,
                    message=SHELL_INTERP_MSG,
                    cwd=cwd,
                )
                if result:
                    return result

        return None

    def _check_one_interpreter(
        self,
        *,
        command: str,
        interpreter: _Interpreter,
        approved: tuple[str, ...],
        message: str,
        cwd: str = "",
    ) -> HookResult | None:
        """Judge ONE command unit — the caller supplies substitution bodies
        as their own units (see `_command_units`), so this never has to
        look inside `$( … )` itself."""
        if interpreter.token not in command:
            return None

        # Heredoc / here-string feeding the interpreter via stdin (GH-687).
        # Checked on the whole command so a `|` inside the heredoc body does
        # not confuse the pipeline split below.
        if interpreter.heredoc.search(command):
            return HookResult(message=message)

        for idx, raw_segment in enumerate(command.split("|")):
            segment = raw_segment.strip()

            try:
                parts = shlex.split(segment)
            except ValueError:
                # Fail closed (GH-687): an unparseable command naming the
                # interpreter is suspicious, not safe. The old `return None`
                # let a quoting trick smuggle execution past the guard.
                # Command position only (GH-971): an argument that merely
                # ends in `.sh` is a read target, not an interpreter.
                if interpreter.command_position.search(command):
                    return HookResult(message=message)
                return None

            parts = strip_command_wrappers(parts=parts)
            if not parts:
                continue
            argv = interpreter.argv_of(parts)
            if argv is None:
                continue

            run, script = interpreter.target(argv)
            if run is _Run.INLINE:
                return HookResult(message=message)
            if run is _Run.MODULE:
                continue

            if script is None:
                # No script file. An upstream pipe makes the interpreter read
                # the piped data as its program (GH-687); a bare interpreter in
                # the first segment is just a REPL — not a script smuggle.
                if idx > 0:
                    return HookResult(message=message)
                continue

            if not Path(script).expanduser().is_absolute():
                continue

            if _is_approved_path(script, approved):
                continue

            if _is_inside_cwd(script=script, cwd=cwd):
                continue

            return HookResult(message=message)

        return None


def _is_inside_cwd(*, script: str, cwd: str) -> bool:
    # GH-1683: `bash /abs/worktree/scripts/x.sh` names the same file as the
    # relative spelling that already passes. resolve() collapses `..` and
    # symlinks so an escape out of the tree is still judged untrusted.
    if not cwd:
        return False
    try:
        root = Path(cwd).resolve()
        if root == Path(root.anchor):
            return False
        return Path(script).expanduser().resolve().is_relative_to(root)
    except (OSError, RuntimeError):
        return False
