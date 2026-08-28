"""Validator: execution safety patterns.

Consolidates validate-bash-security.py (Bash branch) and
block-python3-inline.py.

Blocks:
  1. Shell-based file writes (cat >, echo >, printf >)
  2. In-place file editors (sed -i, perl -i, gawk -i inplace, dd of=)
  3. Interpreter inline code (python3 -c, bash/sh/zsh -c)
  4. Interpreters reading a script via stdin (heredoc/here-string,
     bare `-`, shell `-s`, or a pipe feeding the interpreter) — GH-687
  5. Interpreters running untrusted absolute script paths
     (python3/bash/sh/zsh <untrusted-abs-path>)

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
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.bash_tokens import ENV_VAR_RE, substitution_bodies
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
    "For multi-line commit messages: create a unique file with"
    " /tmp/Dev10x/bin/mktmp.sh git commit-msg .txt,"
    " Write content to the returned path, then git commit -F <path>"
)

INPLACE_EDIT_MSG = (
    "Use the Write/Edit tool instead of in-place stream editors"
    " (sed -i, perl -i, gawk -i inplace, dd of=).\n"
    "Read-only forms are fine: sed -n, sed/awk writing to stdout,"
    " perl -ne/-pe without -i."
)

PYTHON3_INLINE_MSG = """\
\U0001f6ab  python3 inline/stdin/untrusted script blocked.

Use the Write tool to create a self-contained uv script instead:

  Step 1 \u2014 Write the script to /tmp/Dev10x/<name>.py via the Write tool:

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


def _heredoc_into_re(interpreter: str) -> re.Pattern[str]:
    """Match a heredoc/here-string feeding ``interpreter`` via stdin (GH-687).

    The interpreter must appear at a command boundary (start, pipe, ``;``,
    ``&``, ``(``, or newline), optionally preceded by ``VAR=value`` env
    prefixes, and be followed on the same line by ``<<`` (heredoc) or
    ``<<<`` (here-string). Matched on the whole command so a ``|`` inside
    the heredoc body never confuses pipeline splitting.

    Substitutions need no boundary character here (GH-986). Each body is
    passed in as its own unit by :func:`_command_units`, stripped of its
    ``$(``/backtick wrapper, so the interpreter lands at ``^``.
    """
    return re.compile(
        r"(?:^|[|;&(\n])\s*"
        r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*" + re.escape(interpreter) + r"\b[^\n]*?<<"
    )


def _command_position_re(interpreter: str) -> re.Pattern[str]:
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
        r"(?:[\w./~-]*/)?" + re.escape(interpreter) + r"\b"
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


# python3 plus the shell interpreters that already block inline `-c`.
_STDIN_GUARDED_INTERPRETERS = ("python3", *SHELL_INTERPRETERS)
_HEREDOC_INTO = {name: _heredoc_into_re(name) for name in _STDIN_GUARDED_INTERPRETERS}
_COMMAND_POSITION = {name: _command_position_re(name) for name in _STDIN_GUARDED_INTERPRETERS}

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


def _strip_env_prefix(parts: list[str]) -> list[str]:
    i = 0
    while i < len(parts) and ENV_VAR_RE.match(parts[i]):
        i += 1
    return parts[i:]


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
        return self._check_interpreter(command=inp.command)

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

                parts = _strip_env_prefix(parts)
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

            parts = _strip_env_prefix(parts)
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

    def _check_interpreter(self, *, command: str) -> HookResult | None:
        """Block inline code and untrusted absolute script paths for
        python3 and the shell interpreters (bash/sh/zsh).

        python3 keeps its `-m` carve-out and the narrow approved-prefix
        set; the shell interpreters additionally allow /tmp/Dev10x/.
        First match wins (python3 checked before the shells), so the
        interpreter loop stays outermost and each one sweeps every unit
        before the next interpreter is tried.
        """
        units = _command_units(command)

        for unit in units:
            result = self._check_one_interpreter(
                command=unit,
                interpreter="python3",
                approved=APPROVED_ABS_PREFIXES,
                message=PYTHON3_INLINE_MSG,
                allow_module=True,
                dash_s_stdin=False,  # python3 -s is a site-flag, not stdin delivery
            )
            if result:
                return result

        for interpreter in SHELL_INTERPRETERS:
            for unit in units:
                result = self._check_one_interpreter(
                    command=unit,
                    interpreter=interpreter,
                    approved=SHELL_APPROVED_ABS_PREFIXES,
                    message=SHELL_INTERP_MSG,
                    allow_module=False,
                    dash_s_stdin=True,  # bash/sh/zsh -s reads the script from stdin
                )
                if result:
                    return result

        return None

    def _check_one_interpreter(
        self,
        *,
        command: str,
        interpreter: str,
        approved: tuple[str, ...],
        message: str,
        allow_module: bool,
        dash_s_stdin: bool,
    ) -> HookResult | None:
        """Judge ONE command unit — the caller supplies substitution bodies
        as their own units (see `_command_units`), so this never has to
        look inside `$( … )` itself."""
        if interpreter not in command:
            return None

        # Heredoc / here-string feeding the interpreter via stdin (GH-687).
        # Checked on the whole command so a `|` inside the heredoc body does
        # not confuse the pipeline split below.
        if _HEREDOC_INTO[interpreter].search(command):
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
                if _COMMAND_POSITION[interpreter].search(command):
                    return HookResult(message=message)
                return None

            parts = _strip_env_prefix(parts)
            if not parts or parts[0] != interpreter:
                continue

            argv = parts[1:]

            if allow_module and "-m" in argv:
                continue

            if any(a == "-c" or a.startswith("-c") for a in argv):
                return HookResult(message=message)

            # Bare `-` reads the program from stdin for every interpreter;
            # `-s` (possibly clustered, e.g. `-se`) does so for the shells.
            if "-" in argv:
                return HookResult(message=message)
            if dash_s_stdin and any(
                a.startswith("-") and not a.startswith("--") and "s" in a[1:] for a in argv
            ):
                return HookResult(message=message)

            script = next((a for a in argv if not a.startswith("-")), None)

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

            return HookResult(message=message)

        return None
