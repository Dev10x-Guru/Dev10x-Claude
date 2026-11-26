"""Validator: read-only SQL enforcement.

Ported from validate-sql.py.

Validates that db.sh / psql commands contain only read-only SQL.
Blocks direct psycopg2 / postgres:// connections.

``bq query`` gets the same read-only contract (GH-1633): a blanket
``Bash(bq query:*)`` allow auto-approved ``DELETE``/``MERGE`` against
BigQuery while every Postgres path was guarded. This closes that hole at
the hook. Every other ``bq`` verb that writes is refused too, and so is a
flag file the hook cannot read. A schema-first ``bq`` wrapper skill, after
which the raw command moves to deny, is the remaining scope on GH-1633.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

from dev10x.core.db_script import db_script
from dev10x.core.domain import HookInput, HookResult
from dev10x.core.domain.common.bash_tokens import (
    ANY_CASE_ENV_VAR_RE,
    SUBSTITUTION_WORD,
    CommandSegment,
    ProgramProbe,
    UntokenizableCommandError,
    command_position_re,
    command_segments,
    command_units,
    git_exec_commands,
    nested_commands,
    process_substitution_bodies,
    runner_commands,
    runs_script_output,
    shell_command_strings,
    shell_stdin_scripts,
    split_tokens,
    strip_command_wrappers,
    substitution_bodies,
    tmux_command_name,
    typed_stream,
    typed_streams,
    without_shell_quoting,
)
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok
from dev10x.core.domain.profile_tier import ProfileTier
from dev10x.core.validators.base import ValidatorBase

POSTGRES_CONN_RE = re.compile(r"postgres(?:ql)?://[^'\"\s]+:[^@'\"\s]+@[a-zA-Z0-9._-]+")

BLOCKED_KEYWORDS = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|"
    r"GRANT|REVOKE|VACUUM|REINDEX|CLUSTER|COPY|"
    r"DO\s*\$|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|"
    r"SET\s+(?!search_path|statement_timeout|default_transaction_read_only)|"
    r"LOCK|DISCARD|RESET|"
    r"COMMENT\s+ON|SECURITY\s+LABEL|REASSIGN|"
    r"REFRESH\s+MATERIALIZED|"
    # SELECT-shaped but destructive: these kill live sessions, and a
    # teardown script reaches for them when a DROP fails on an open
    # connection (GH-1034).
    r"pg_terminate_backend|pg_cancel_backend"
    r")\b",
    re.IGNORECASE,
)

SAFE_PREFIXES = re.compile(
    r"^\s*(SELECT|WITH|EXPLAIN|SHOW|\\d|\\dt|\\l)\b",
    re.IGNORECASE,
)

_PLUGIN_ROOT = Path(
    os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        str(Path(__file__).resolve().parents[4]),
    )
)
DB_SH_PATH = _PLUGIN_ROOT / db_script(plugin_root=_PLUGIN_ROOT)

DIRECT_CONN_MSG = (
    "BLOCKED: Direct database connection via psycopg2 or postgres:// URL "
    "is not allowed.\n"
    "Database writes are NEVER permitted. For read-only queries use "
    f"{DB_SH_PATH}.\n"
    "If database writes are needed, provide the SQL to the user to run manually."
)

# BigQuery statements the Postgres denylist does not name. `CALL` runs a
# stored procedure whose body this hook cannot see.
BQ_BLOCKED_KEYWORDS = re.compile(
    r"\b(MERGE|EXPORT\s+DATA|LOAD\s+DATA|EXECUTE\s+IMMEDIATE|CALL)\b",
    re.IGNORECASE,
)

# `bq query` flags that make even a SELECT write: its result lands in a
# table, or it is registered to run again later.
_BQ_WRITE_FLAGS = frozenset({"--destination_table", "--replace", "--append_table", "--schedule"})

# `bq` flags that take their value as the NEXT token, so the value is not
# mistaken for query text. `--flag=value` is one token and needs no entry.
# An unknown spaced flag leaks its value into the SQL, which then fails
# the SELECT-prefix check: the fail-closed direction.
_BQ_VALUE_FLAGS = frozenset(
    {
        "--format",
        "--max_rows",
        "-n",
        "--project_id",
        "--dataset_id",
        "--location",
        "--parameter",
        "--label",
        "--job_id",
        "--maximum_bytes_billed",
        "--max_statement_results",
        "--job_timeout_ms",
        "--session_id",
        "--connection_property",
        "--reservation_id",
        "--api",
        "--api_version",
        "--bigqueryrc",
        "--service_account",
        "--credential_file",
        "--destination_table",
        "--destination_kms_key",
        "--schedule",
        "--display_name",
        "--target_dataset",
        "--udf_resource",
        "--external_table_definition",
    }
)

_BQ_FLAG_FILE_FLAGS = frozenset({"--flagfile", "--bigqueryrc"})
_BQ_RC_ENV = "BIGQUERYRC"

# `bq` global flags that take no value, so the word after one is the verb.
# absl's `--noX` spelling exists only for booleans and is read the same way.
_BQ_BOOLEAN_FLAGS = frozenset(
    {
        "--help",
        "--helpshort",
        "--helpfull",
        "--helpxml",
        "-h",
        "--quiet",
        "-q",
        "--headless",
        "--sync",
        "--synchronous_mode",
        "--debug_mode",
        "--use_gce_service_account",
        "--enable_gdrive",
        "--use_regional_endpoints",
        "--disable_ssl_validation",
        "--fingerprint_job_id",
        "--enable_resumable_uploads",
        "--use_google_auth",
        "--version",
    }
)
_BQ_GLOBAL_VALUE_FLAGS = _BQ_VALUE_FLAGS | {
    "--apilog",
    "--ca_certificates_file",
    "--discovery_file",
    "--trace",
    "--httplib2_debuglevel",
    "--application_default_credential_file",
    "--oauth_access_token",
    "--universe_domain",
}

# `bq` commands that change nothing. Every other verb (`rm`, `load`, `cp`,
# `mk`, `update`, `insert`, `extract`, `truncate`, `undelete`, `cancel`,
# `init`, `shell`, `partition`, the IAM writers, and any verb added later)
# is refused.
_BQ_READ_ONLY_VERBS = frozenset(
    {"ls", "show", "head", "query", "version", "help", "info", "wait", "get-iam-policy"}
)

_BQ_WORD_RE = re.compile(r"(?<![\w.-])bq(?![\w.-])")
_BQ_LETTERS_WINDOW = 1024
_BQ_LETTERS_MAX_CALLS = 64
_BQ_LETTERS_END_RE = re.compile(r"[;&|\n)`]")

BQ_FLAG_FILE_DETAIL = (
    "--flagfile, --bigqueryrc and BIGQUERYRC load bq flags from a file this "
    "hook cannot read, and such a file can turn a SELECT into a write. The "
    "default ~/.bigqueryrc is outside this check."
)

BQ_STDIN_MSG = (
    "BLOCKED: `bq query` without inline SQL reads the query from stdin, "
    "which the read-only check cannot inspect.\n"
    "Pass the SELECT as the final argument instead: "
    "bq query --nouse_legacy_sql 'SELECT …'"
)


def _bq_write_message(*, detail: str) -> str:
    return (
        f"BLOCKED by db safety hook: {detail}\n\n"
        "BigQuery access is read-only (GH-1633). Print the statement for the "
        "user to run manually. Pass flag values as --flag=value."
    )


DIRECT_PSQL_MSG = (
    "BLOCKED: Direct psql calls are not allowed. "
    f"Use {DB_SH_PATH} instead.\n"
    f"Example: {DB_SH_PATH} mydb "
    '"SELECT count(*) FROM my_table"'
)


def _is_psql_binary(token: str) -> bool:
    return token == "psql" or token.endswith("/psql")


# A word that hands psql to something else to run (GH-2001): a command
# string that opens on it (`tmux send-keys -l 'psql -d x'`, a trailing
# `\n` typed into screen), or a value that names it as a program
# (`core.pager=psql`, `GIT_PAGER=/usr/bin/psql`, `alias.x=!psql`).
_PSQL_PATH = r"(?:[^\s'\"=!|]*/)?psql"
_PSQL_LEADS_RE = re.compile(rf"^\s*{_PSQL_PATH}(?=$|\s|\\|\^|;|&|\|)")
_PSQL_AS_VALUE_RE = re.compile(rf"[=!|]\s*['\"]?{_PSQL_PATH}(?![\w.-])")


def _names_psql(token: str) -> bool:
    return (
        _is_psql_binary(token)
        or bool(_PSQL_LEADS_RE.match(token))
        or bool(_PSQL_AS_VALUE_RE.search(token))
    )


# A shell or `env` assignment whose value a program may run: GIT_PAGER,
# EDITOR, LESSOPEN, GIT_CONFIG_VALUE_0 … Every name counts, not a list of
# known ones, so an unlisted variable cannot slip through (GH-2001).
# Unlike ANY_CASE_ENV_VAR_RE, a quoted value may hold blanks.
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(.+)$", re.DOTALL)
_ASSIGNED_PROGRAM_PREFIXES = "|!"
# A value computed by a substitution: `GIT_PAGER=$(…)`, `core.pager=`…``.
_SUBSTITUTED_VALUE_RE = re.compile(r"[=!]['\"]?(?:\$\(|`)")
# A substitution left in a word: raw inside double quotes, or the
# lexer's SUBSTITUTION_WORD placeholder.
_SUBSTITUTION_RE = re.compile(rf"\$\(|`|{re.escape(SUBSTITUTION_WORD)}")
# A script runner handed a substitution's output: `eval "$(…)"`,
# `source <(…)`, `bash <(…)`. The output may spell psql with no `psql` in
# the raw text, so the walk runs (GH-2005).
_SCRIPT_RUNNER_RE = re.compile(
    r"\b(?:eval|source|bash|sh|zsh|dash|ksh|csh|tcsh|fish|ash|rbash|mksh)\s"
    r"|(?:^|[;&|(\n])\s*\.\s"
)
_ANY_SUBSTITUTION_RE = re.compile(r"\$\(|`|[<>]\(")


def _runs_substitution(*, command: str) -> bool:
    return bool(_ANY_SUBSTITUTION_RE.search(command)) and bool(
        _SCRIPT_RUNNER_RE.search(without_shell_quoting(text=command))
    )


# Keystrokes typed through an opaque runner (cursor moves, history keys)
# can reorder what was typed, so its letters are judged as a multiset.
_PSQL_LETTERS = frozenset("psql")

_PSQL_PROBE = ProgramProbe.for_program(program="psql")
# screen and tmux type keystrokes that may spell psql with no `psql` in
# the raw text: `tmux send-keys -H 70 73 71 6c 0a`, `stuff '\160sql'`.
_KEYSTROKE_RUNNER_PROBE = ProgramProbe.for_program(program="screen|tmux")
# Fail-closed fallback for a unit the segmenter cannot tokenize.
_PSQL_COMMAND_POSITION_RE = command_position_re(program="psql")


# Programs that only search or print their operands, so a `psql` token after
# one of them is a pattern or text: `rg -n 'psql' projects.yaml` (GH-1790).
_TEXT_ONLY_EXECUTABLES = frozenset(
    {"ack", "ag", "cat", "echo", "egrep", "fgrep", "grep", "head", "printf", "rg", "tail", "wc"}
)
# A text tool counts only by bare name or from a system bin directory:
# `./cat psql` or `/tmp/x/cat psql` runs whatever that file is.
_SYSTEM_BIN_DIRS = frozenset({"/bin", "/usr/bin", "/usr/local/bin"})
# A segment that chains, substitutes, opens a subshell or process
# substitution (`cat <( psql … )`), backgrounds, or spans a heredoc line
# may run psql after the search tool; `rg --pre`, `rg --hostname-bin` and
# `ag/ack --pager` run a program of their own. None of these is exempt.
_EXEMPTION_BREAKERS_RE = re.compile(r"&|;|\n|`|[()]|--pre|--pager|--hostname-bin")


def _is_text_only_program(word: str) -> bool:
    directory, _, name = word.rpartition("/")
    return name in _TEXT_ONLY_EXECUTABLES and (not directory or directory in _SYSTEM_BIN_DIRS)


def _psql_is_an_operand(*, segment: str, parts: list[str]) -> bool:
    if _EXEMPTION_BREAKERS_RE.search(segment):
        return False
    words = strip_command_wrappers(parts=parts)
    return bool(words) and _is_text_only_program(words[0])


def _psql_word_anywhere(*, command: str) -> bool:
    """The fail-closed word rule: any bare ``psql`` word blocks (GH-1809).

    Only a plain segment headed by a text tool is exempt, and a
    ``docker exec`` / ``op run`` segment is left to the wrapped-write
    check. The command-position walk adds blocks on top of this rule and
    never removes one, so nothing this rule blocks can pass.
    """
    for segment in _split_pipe_segments(command):
        segment = segment.strip()
        try:
            parts = shlex.split(segment)
        except ValueError:
            parts = []
        if _is_exempt_psql_wrapper(parts):
            continue
        if any(_names_psql(token) for token in parts) and not _psql_is_an_operand(
            segment=segment, parts=parts
        ):
            return True
    return False


def _runs_psql(parts: list[str]) -> bool:
    words = strip_command_wrappers(parts=parts)
    return bool(words) and _is_psql_binary(words[0])


@dataclass(frozen=True)
class _PsqlUnit:
    text: str
    segments: tuple[CommandSegment, ...] | None
    opaque: bool = False


def _assigned_programs(*, parts: list[str]) -> list[str]:
    """Values assigned anywhere in ``parts``, read as programs (GH-2001).

    Covers the prefix (``GIT_PAGER=psql git log``), ``env``/``sudo``
    assignments and ``export``/``declare``/``alias`` arguments. A text
    tool's operand (``echo PAGER=psql``) is text, not an assignment.
    """
    program = strip_command_wrappers(parts=parts)
    if program and _is_text_only_program(program[0]):
        return []
    values = [match.group(1) for token in parts if (match := _ASSIGNMENT_RE.match(token))]
    # A value may itself list `key=value` pairs whose values git runs:
    # GIT_CONFIG_PARAMETERS="'core.pager'='psql'" (GH-2005).
    pairs = [
        word.partition("=")[2]
        for value in values
        for word in split_tokens(command=value)
        if "=" in word
    ]
    return [value.lstrip(_ASSIGNED_PROGRAM_PREFIXES) for value in (*values, *pairs)]


# tmux and screen commands whose arguments are themselves a tmux/screen
# command line or a shell command: `if-shell true 'run-shell psql'`,
# `bind x exec psql`. Every argument of a keystroke runner is judged as a
# command (`display-popup -E psql`, `set-buffer` + `paste-buffer`,
# `register` + `paste`), and these are read one level deeper (GH-2001).
_KEYSTROKE_RUNNERS = frozenset({"tmux", "screen"})
_KEYSTROKE_NESTING_COMMANDS = frozenset(
    {"if-shell", "if", "run-shell", "run", "display-popup", "popup", "pipe-pane", "pipep"}
    | {"bind-key", "bind", "confirm-before", "confirm", "command-prompt", "display-menu"}
    | {"menu", "new-session", "new", "new-window", "neww", "split-window", "splitw"}
    | {"respawn-pane", "respawnp", "respawn-window", "respawnw", "send-keys", "send"}
    | {"set-buffer", "setb", "set-hook", "eval", "stuff", "register", "exec", "screen"}
)


def _runner_argument_words(*, words: list[str]) -> list[str]:
    found: list[str] = []
    for word in words:
        if word.startswith("-"):
            continue
        found.append(word)
        inner = split_tokens(command=word)
        if len(inner) > 1 and (
            inner[0] in _KEYSTROKE_NESTING_COMMANDS
            or tmux_command_name(token=inner[0]) in _KEYSTROKE_NESTING_COMMANDS
        ):
            found.extend(_runner_argument_words(words=inner[1:]))
    return found


def _keystroke_runner_words(*, parts: list[str]) -> list[str]:
    start = next(
        (idx for idx, token in enumerate(parts) if Path(token).name in _KEYSTROKE_RUNNERS),
        None,
    )
    program = strip_command_wrappers(parts=parts)
    if start is None or (program and _is_text_only_program(program[0])):
        return []
    return _runner_argument_words(words=parts[start + 1 :])


UNTOKENIZABLE_RUNNER_MSG = (
    "BLOCKED: this command types keystrokes into a terminal (screen/tmux) or "
    "sets a program-running value (git -c, GIT_PAGER=…) next to psql, and it "
    "could not be tokenized, so what it runs cannot be checked.\n"
    f"Fix the quoting, or use {DB_SH_PATH} for read-only queries."
)
# Fail-closed reading of an untokenizable unit (GH-2001): a keystroke
# runner in command position, or a git/assignment program slot beside the
# letters of psql.
_KEYSTROKE_POSITION_RE = command_position_re(program="screen|tmux")
_PROGRAM_SLOT_RE = re.compile(r"\bgit\b|[A-Za-z_][A-Za-z0-9_]*=")


def _hides_a_program(*, text: str) -> bool:
    if _KEYSTROKE_POSITION_RE.search(text):
        return True
    return bool(_PROGRAM_SLOT_RE.search(text)) and _PSQL_LETTERS <= set(
        without_shell_quoting(text=text)
    )


def _spells_psql(*, unit: _PsqlUnit) -> bool:
    return unit.opaque and _PSQL_LETTERS <= set(unit.text)


# Hard caps on what one hook call may expand. A hook that runs past its
# timeout is killed, and a killed hook is not a block, so a command too
# nested to judge in time is blocked up front instead (GH-2005).
_MAX_COMMAND_CHARS = 64 * 1024
_MAX_UNITS = 512
_MAX_LEXED_CHARS = 256 * 1024
_MAX_DEPTH = 32
_MAX_OPERAND_SUFFIXES = 64
_MAX_FALLBACK_CHARS = 4 * 1024

TOO_COMPLEX_MSG = (
    "BLOCKED: this command is too complex for DX004 to judge: it nests more "
    f"runners, scripts or values than the hook can expand in time (over "
    f"{_MAX_UNITS} units, depth {_MAX_DEPTH}, {_MAX_COMMAND_CHARS} characters, "
    f"{_MAX_OPERAND_SUFFIXES} operands of an unknown program, or an unparseable "
    f"part over {_MAX_FALLBACK_CHARS} characters).\n"
    f"Split it into simpler commands, or use {DB_SH_PATH} for read-only queries."
)


class _TooComplexError(Exception):
    """A command exceeded a DX004 expansion cap; the caller blocks it."""


def _cap_fallback(*, text: str) -> None:
    """Refuse a long untokenizable unit before a command-position regex
    reads it: that search is quadratic on `ssh -o a -o a …` (GH-2005)."""
    if len(text) > _MAX_FALLBACK_CHARS:
        raise _TooComplexError


@dataclass
class _WalkBudget:
    """Units and characters one DX004 check has expanded so far."""

    units: int = 0
    chars: int = 0

    def charge(self, *, text: str, depth: int) -> None:
        self.units += 1
        self.chars += len(text)
        if (
            self.units > _MAX_UNITS
            or self.chars > _MAX_LEXED_CHARS
            or depth > _MAX_DEPTH
            or len(text) > _MAX_COMMAND_CHARS
        ):
            raise _TooComplexError


def _unknown_program_operands(*, words: list[str]) -> list[str]:
    """Every operand suffix of a program run from a path the hook cannot vouch for.

    ``./git psql`` or ``/tmp/x/cat psql`` runs whatever that file is, so each
    suffix starting at a plain word is a candidate command line, re-read
    by the shell as ``ssh`` does (GH-2005). A bare name or a system bin
    path is left to the runner tables.
    """
    if not words or "/" not in words[0]:
        return []
    directory = words[0].rpartition("/")[0]
    if directory in _SYSTEM_BIN_DIRS:
        return []
    operands = words[1:]
    starts = [start for start, word in enumerate(operands) if not word.startswith("-")]
    if len(starts) > _MAX_OPERAND_SUFFIXES:
        raise _TooComplexError
    return [" ".join(operands[start:]) for start in starts]


def _host_wrapped_commands(*, parts: list[str]) -> list[str]:
    """What ``op run`` wraps, unless it is psql itself (GH-2005 review F5).

    ``op run`` executes on this host, so ``op run -- bash -c 'psql …'`` is a
    host shell. Only a wrapped psql keeps the exemption and goes to the
    wrapped-write check. ``docker exec`` runs inside its container and
    hands over nothing.
    """
    if Path(parts[0]).name != "op":
        return []
    return [
        nested.command
        for nested in nested_commands(parts=parts)
        if not _runs_psql(split_tokens(command=nested.command))
    ]


def _script_commands(*, segment: CommandSegment) -> list[str]:
    """Commands ``segment`` runs as a script: a shell's ``-c`` string, its
    heredoc or here-string, git's exec forms, an unknown program's operands
    (GH-2005)."""
    parts = list(segment.argv)
    words = strip_command_wrappers(parts=parts)
    return [
        *shell_command_strings(parts=parts),
        *shell_stdin_scripts(segment=segment),
        *git_exec_commands(parts=words),
        *_unknown_program_operands(words=words),
    ]


def _psql_units(*, command: str, budget: _WalkBudget) -> Iterator[_PsqlUnit]:
    """Every unit ``command`` runs, with its segments (``None`` if untokenizable).

    Like :func:`command_units`, but a ``docker exec`` / ``op run`` segment
    hands over no nested unit: its psql is judged by the wrapped-write
    check instead of the direct-psql gate (GH-1809). Every other runner
    (``ssh``, ``watch``, ``eval``, ``kubectl exec`` …) nests as usual, and
    so do typed keystrokes, git's configured programs and assigned
    variables (GH-2001).
    """
    seen: set[tuple[str, bool]] = set()
    pending: list[tuple[str, bool, int]] = [(command, False, 0)]
    while pending:
        unit, opaque, depth = pending.pop()
        if (unit, opaque) in seen or not unit.strip():
            continue
        seen.add((unit, opaque))
        budget.charge(text=unit, depth=depth)
        child = depth + 1
        bodies = substitution_bodies(unit, include_backticks=True)
        pending.extend((body, False, child) for body in bodies)
        try:
            segments = command_segments(command=unit)
        except UntokenizableCommandError:
            yield _PsqlUnit(text=unit, segments=None, opaque=opaque)
            continue
        yield _PsqlUnit(text=unit, segments=segments, opaque=opaque)
        pending.extend(
            (stream.command, stream.opaque, child)
            for stream in typed_stream(segments=[segment.argv for segment in segments])
        )
        runs_output = False
        computes_value = False
        substituted_value = bool(_SUBSTITUTED_VALUE_RE.search(unit))
        for segment in segments:
            parts = list(segment.argv)
            if _is_exempt_psql_wrapper(parts):
                pending.extend(
                    (wrapped, False, child) for wrapped in _host_wrapped_commands(parts=parts)
                )
                continue
            nested = runner_commands(parts=parts)
            slots = [
                *(candidate.command for candidate in nested),
                *_assigned_programs(parts=parts),
                *_keystroke_runner_words(parts=parts),
                *_script_commands(segment=segment),
            ]
            runs_output = runs_output or runs_script_output(parts=parts)
            pending.extend((candidate.command, candidate.opaque, child) for candidate in nested)
            pending.extend((slot, False, child) for slot in slots[len(nested) :])
            computes_value = (
                computes_value
                or substituted_value
                or any(_SUBSTITUTION_RE.search(slot) for slot in slots)
            )
        if runs_output:
            # `source <(echo psql …)` runs what the body prints, so the
            # body is judged by its letters (GH-2005).
            pending.extend((body, True, child) for body in process_substitution_bodies(unit))
        if computes_value:
            # The output names the program (`GIT_PAGER=$(echo psql)`),
            # so the producing body is judged by its letters.
            pending.extend((body, True, child) for body in bodies)


def _is_exempt_psql_wrapper(parts: list[str]) -> bool:
    """psql wrapped by ``docker exec`` or ``op run`` is exempt (GH-474 #4).

    ``docker exec <container> psql …`` runs inside a container — the container,
    not the host hook, is the trust boundary — and ``op run -- psql …`` routes
    through the sanctioned 1Password secrets wrapper. Neither is a direct host
    psql call, so the *direct-psql* gate does not apply.

    The exemption covers reads only. A wrapped invocation still has its SQL
    checked by :func:`_check_wrapped_psql_writes` — see GH-1034.
    """
    if not parts:
        return False
    command = Path(parts[0]).name
    if command == "docker" and "exec" in parts[1:]:
        return True
    if command == "op" and "run" in parts[1:]:
        return True
    return False


# psql short options that consume a value. getopt ends a bundle at the
# first such letter, so `-tAc "SELECT 1"` is `-t -A -c "SELECT 1"` and
# `-cSELECT 1` attaches the value directly. Without the full set, a
# bundle like `-tAf` would be read as flags and its file argument missed.
_PSQL_VALUE_OPTS = frozenset("cdfFhLoPpRTUv")
_PSQL_SQL_OPT = "c"
_PSQL_FILE_OPT = "f"

WRAPPED_SCRIPT_MSG = (
    "BLOCKED: psql -f/--file runs a script whose contents cannot be checked "
    "at match time, so it is treated as a write.\n"
    f"For read-only queries use {DB_SH_PATH}.\n"
    "If the script performs writes, provide it to the user to run manually."
)

WRAPPED_WRITE_HINT = (
    "The docker exec / op run exemption covers reads only — a wrapped write "
    "is still a write. Print the SQL for the user to run manually."
)


def _psql_args(parts: list[str]) -> list[str]:
    """Tokens the wrapped ``psql`` binary itself receives.

    Slicing at the binary keeps wrapper flags (``op run --env-file=…``) out
    of the flag scan, so they cannot be mistaken for psql's own ``--file``.
    """
    for i, token in enumerate(parts):
        if _is_psql_binary(token):
            return parts[i + 1 :]
    return []


def _split_short_bundle(arg: str) -> tuple[str, str]:
    """Split a getopt short bundle into (option letters, attached value).

    Scanning stops at the first value-taking letter, which owns the rest
    of the token: ``-tAc`` → ``("tAc", "")`` and ``-cSELECT 1`` →
    ``("c", "SELECT 1")``.
    """
    body = arg[1:]
    for i, letter in enumerate(body):
        if letter in _PSQL_VALUE_OPTS:
            return body[: i + 1], body[i + 1 :]
    return body, ""


def _scan_psql_options(args: list[str]) -> tuple[list[str], bool]:
    """Return the inline SQL statements and whether a script file is read."""
    statements: list[str] = []
    reads_file = False
    i = 0
    while i < len(args):
        arg = args[i]
        step = 1
        if arg.startswith("--command="):
            statements.append(arg.split("=", 1)[1])
        elif arg == "--command":
            if i + 1 < len(args):
                statements.append(args[i + 1])
            step = 2
        elif arg.startswith("--file="):
            reads_file = True
        elif arg == "--file":
            reads_file = True
            step = 2
        elif arg.startswith("-") and not arg.startswith("--"):
            letters, attached = _split_short_bundle(arg)
            value = attached or (args[i + 1] if i + 1 < len(args) else "")
            if letters.endswith(_PSQL_FILE_OPT):
                reads_file = True
            elif letters.endswith(_PSQL_SQL_OPT):
                statements.append(value)
            if not attached and letters and letters[-1] in _PSQL_VALUE_OPTS:
                # The value is a separate token. Skipping it also keeps any
                # other value-taking option from having its argument read as
                # a flag (`-U drop_user`).
                step = 2
        i += step
    return statements, reads_file


def _check_wrapped_psql_writes(*, parts: list[str]) -> HookResult | None:
    """Apply the read-only contract to psql running behind an exempt wrapper."""
    args = _psql_args(parts)
    if not args:
        return None
    statements, reads_file = _scan_psql_options(args)
    if reads_file:
        return HookResult(message=WRAPPED_SCRIPT_MSG)
    for sql in statements:
        result = _validate_sql(sql)
        if isinstance(result, ErrorResult):
            return HookResult(
                message=(f"BLOCKED by db safety hook: {result.error}\n\n{WRAPPED_WRITE_HINT}")
            )
    return None


def _is_db_sh(token: str) -> bool:
    return token.endswith("db.sh") or token.endswith("/db.sh")


def _split_pipe_segments(command: str) -> list[str]:
    segments: list[str] = []
    current_start = 0
    in_single = False
    in_double = False
    escape = False
    for i, ch in enumerate(command):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "|" and not in_single and not in_double:
            segments.append(command[current_start:i])
            current_start = i + 1
    segments.append(command[current_start:])
    return segments


def _extract_sql_from_command(command: str) -> str | None:
    first_cmd = _split_pipe_segments(command)[0].strip()

    try:
        parts = shlex.split(first_cmd)
    except ValueError:
        return None

    if not parts:
        return None

    if not _is_db_sh(parts[0]):
        return None

    if "--list" in parts or "-l" in parts:
        return None
    if "-f" in parts or "--file" in parts:
        flag_idx = next(
            (i for i, p in enumerate(parts) if p in ("-f", "--file")),
            None,
        )
        if flag_idx is not None and flag_idx + 1 < len(parts):
            sql_file = parts[flag_idx + 1]
            try:
                with open(sql_file) as fh:
                    return fh.read()
            except OSError:
                return None
        return None
    remaining = parts[1:]
    if len(remaining) >= 2:
        return remaining[1]
    return None


_SINGLE_QUOTED_RE = re.compile(r"'[^']*'")


def _validate_sql(sql: str) -> Result[dict[str, Any]]:
    stripped = sql.strip().rstrip(";").strip()

    if not stripped:
        return ok({})

    without_strings = _SINGLE_QUOTED_RE.sub("", stripped)
    if ";" in without_strings:
        return err(
            "Multi-statement SQL is not allowed.\n"
            "Submit one statement at a time.\n\n"
            f"Blocked SQL:\n{sql}"
        )

    if not SAFE_PREFIXES.match(stripped):
        return err(
            "Query does not start with SELECT/WITH/EXPLAIN/SHOW.\n"
            "Only read-only queries are allowed.\n\n"
            f"Blocked SQL:\n{sql}"
        )

    match = BLOCKED_KEYWORDS.search(stripped)
    if match:
        keyword = match.group(0).upper()
        return err(
            f"Query contains blocked keyword: {keyword}\n"
            "Only read-only queries are allowed.\n\n"
            f"Blocked SQL:\n{sql}"
        )

    return ok({})


def _bq_query_args(parts: list[str]) -> list[str] | None:
    """Everything after ``query`` when ``parts`` runs ``bq query``, else ``None``.

    Env assignments and process wrappers are stripped first, so
    ``CLOUDSDK_CORE_PROJECT=p bq query …`` or ``timeout 60 bq query …``
    is judged as the ``bq`` call it is.
    """
    parts = strip_command_wrappers(parts=parts)
    if not parts or Path(parts[0]).name != "bq" or "query" not in parts[1:]:
        return None
    return parts[parts.index("query", 1) + 1 :]


def _bq_flag_name(token: str) -> str:
    """``token``'s flag name in ``--long`` form.

    bq parses flags with absl, which accepts a long flag behind one dash
    (``-destination_table=t``) as readily as two, so lookups against the
    ``--`` spelling alone are an evasion.
    """
    name = token.partition("=")[0]
    if name.startswith("-") and not name.startswith("--") and len(name) > 2:
        return f"-{name}"
    return name


def _check_bq_query(*, args: list[str]) -> HookResult | None:
    """Judge ``bq query``'s own arguments.

    ``args`` come from a :class:`CommandSegment`, whose argv carries no
    redirect words (GH-1798), so ``bq query < q.sql`` reaches here with no
    SQL at all and is refused as a stdin read.
    """
    if [_bq_flag_name(token) for token in args] == ["--help"]:
        return None
    sql_tokens: list[str] = []
    remaining = iter(args)
    for token in remaining:
        flag = _bq_flag_name(token)
        if flag in _BQ_WRITE_FLAGS:
            return HookResult(message=_bq_write_message(detail=f"{flag} writes a table."))
        if "=" not in token and flag in _BQ_VALUE_FLAGS:
            next(remaining, None)
            continue
        if token.startswith("-"):
            continue
        sql_tokens.append(token)

    if not sql_tokens:
        return HookResult(message=BQ_STDIN_MSG)

    sql = " ".join(sql_tokens)
    result = _validate_sql(sql)
    if isinstance(result, ErrorResult):
        return HookResult(message=_bq_write_message(detail=result.error))
    match = BQ_BLOCKED_KEYWORDS.search(sql)
    if match:
        keyword = " ".join(match.group(0).upper().split())
        return HookResult(
            message=_bq_write_message(detail=f"Query contains blocked keyword: {keyword}")
        )
    return None


@dataclass(frozen=True)
class _BqCall:
    verb: str | None
    operands: tuple[str, ...]
    unsure_flag: str | None


def _bq_call(*, args: list[str]) -> _BqCall:
    """The verb of ``bq <args>``, past its global flags.

    A spaced flag the hook does not know may take the next word as its
    value, so the verb cannot be told and ``unsure_flag`` names it.
    """
    tokens = iter(args)
    for token in tokens:
        if token == "--":
            return _BqCall(verb=next(tokens, None), operands=tuple(tokens), unsure_flag=None)
        if not token.startswith("-") or token == "-":
            return _BqCall(verb=token, operands=tuple(tokens), unsure_flag=None)
        flag = _bq_flag_name(token)
        if "=" in token or flag in _BQ_BOOLEAN_FLAGS or flag.startswith("--no"):
            continue
        if flag in _BQ_GLOBAL_VALUE_FLAGS:
            next(tokens, None)
            continue
        return _BqCall(verb=None, operands=(), unsure_flag=flag)
    return _BqCall(verb=None, operands=(), unsure_flag=None)


def _bq_call_verdict(*, args: list[str]) -> HookResult | None:
    """Refuse a flag file, an unreadable verb or a verb that writes (GH-1633)."""
    if any(_bq_flag_name(token) in _BQ_FLAG_FILE_FLAGS for token in args):
        return HookResult(message=_bq_write_message(detail=BQ_FLAG_FILE_DETAIL))
    call = _bq_call(args=args)
    if call.unsure_flag:
        return HookResult(
            message=_bq_write_message(
                detail=f"{call.unsure_flag} before the bq command hides which command runs."
            )
        )
    if call.verb is not None and call.verb not in _BQ_READ_ONLY_VERBS:
        return HookResult(
            message=_bq_write_message(
                detail=(
                    f"`bq {call.verb}` is not a read-only bq command. Allowed: "
                    + ", ".join(sorted(_BQ_READ_ONLY_VERBS))
                    + "."
                )
            )
        )
    return None


def _check_bq_segment(*, parts: list[str]) -> HookResult | None:
    words = strip_command_wrappers(parts=parts)
    if not words or Path(words[0]).name != "bq":
        return None
    result = _bq_call_verdict(args=words[1:])
    if result:
        return result
    call = _bq_call(args=words[1:])
    if call.verb == "help" and len(call.operands) <= 1:
        return None
    args = _bq_query_args(parts)
    if args is None:
        return None
    return _check_bq_query(args=args)


def _bq_letters_verdict(*, text: str, pattern: re.Pattern[str]) -> HookResult | None:
    """Judge each ``bq`` call in ``text`` by its words, for text the lexer
    cannot split or whose output runs as a command (GH-1633)."""
    for count, match in enumerate(pattern.finditer(text)):
        window = text[match.end() : match.end() + _BQ_LETTERS_WINDOW]
        call_text = _BQ_LETTERS_END_RE.split(window, maxsplit=1)[0]
        if count >= _BQ_LETTERS_MAX_CALLS or len(call_text) == _BQ_LETTERS_WINDOW:
            return HookResult(message=TOO_COMPLEX_MSG)
        args = [token.strip("'\"") for token in call_text.split()]
        result = _bq_call_verdict(args=args)
        if result:
            return result
        if _bq_call(args=args).verb == "query":
            return HookResult(message=_bq_write_message(detail=BQ_UNTOKENIZABLE_DETAIL))
    return None


def _bq_units(*, command: str) -> list[tuple[str, bool]]:
    """Every unit ``command`` runs, with whether its output runs too.

    Joins the shared walk with DX004's own, which also reads shell ``-c``
    strings, heredocs and git's exec forms (GH-2005).
    """
    units = dict.fromkeys((unit, False) for unit in command_units(command=command))
    units.update(
        dict.fromkeys(
            (unit.text, unit.opaque) for unit in _psql_units(command=command, budget=_WalkBudget())
        )
    )
    return list(units)


_BQ_PROBE = ProgramProbe.for_program(program="bq")
_BQ_POSITION_RE = command_position_re(program="bq")

# Fail-closed fallback for a unit the segmenter cannot tokenize: a `bq`
# call in command position that names the `query` subcommand.
_BQ_QUERY_POSITION_RE = re.compile(command_position_re(program="bq").pattern + r"[^\n]*\bquery\b")
BQ_UNTOKENIZABLE_DETAIL = (
    "`bq query` could not be tokenized, so its flags cannot be checked for a write."
)

# Postgres client binaries that write a cluster without any SQL keyword
# reaching this validator (GH-1732). Each is the CLI twin of a statement
# the denylist already blocks: DROP/CREATE DATABASE, DROP/CREATE ROLE,
# VACUUM, REINDEX, CLUSTER.
# pgbench runs update transactions by default and rebuilds its tables
# with -i, so it writes too.
_PG_WRITE_BINARIES = frozenset(
    {
        "dropdb",
        "createdb",
        "dropuser",
        "createuser",
        "vacuumdb",
        "reindexdb",
        "clusterdb",
        "pgbench",
    }
)
_PG_RESTORE = "pg_restore"
_PG_BINARIES = _PG_WRITE_BINARIES | {_PG_RESTORE}
_PG_BINARY_PROBE = ProgramProbe.for_program(program="|".join(sorted(_PG_BINARIES)))

# Fail-closed fallback when a unit cannot be tokenized: a write binary in
# command position, optionally behind env assignments, wrappers or a path.
_PG_COMMAND_POSITION_RE = command_position_re(program="|".join(sorted(_PG_WRITE_BINARIES)))

# `command -v NAME` looks a binary up; it does not run it.
_COMMAND_PROBE_FLAGS = frozenset({"-v", "-V"})

# pg_restore short options that consume a value. A bundle ends at the
# first one, so `-cd app` reaches `d` while `-fd` is `-f` with value `d`.
_PG_RESTORE_VALUE_LETTERS = frozenset("dfFIjLnNPStTUhp")

PG_WRITE_BINARY_MSG = (
    "BLOCKED by db safety hook: `{binary}` writes to a Postgres cluster "
    "(GH-1732).\n"
    "Database writes are NEVER permitted, whether spelled as SQL or as a "
    "client binary. Print the command for the user to run manually."
)


def _pg_restore_targets_database(args: list[str]) -> bool:
    """True when ``pg_restore`` restores into a database, not to a file.

    Without ``-d``/``--dbname`` it only prints a script (or a listing),
    which is a read; ``--clean`` alone just adds DROP lines to that text.
    """
    for arg in args:
        if arg.startswith("--"):
            # getopt_long accepts any unambiguous prefix (`--db=app`).
            # `--d` alone is ambiguous with --data-only and is rejected by
            # pg_restore itself, so two letters are the shortest prefix.
            name = arg[2:].partition("=")[0]
            if len(name) >= 2 and "dbname".startswith(name):
                return True
            continue
        if not arg.startswith("-"):
            continue
        for letter in arg[1:]:
            if letter == "d":
                return True
            if letter in _PG_RESTORE_VALUE_LETTERS:
                break
    return False


def _is_command_probe(*, parts: list[str]) -> bool:
    head = [token for token in parts if not ANY_CASE_ENV_VAR_RE.match(token)][:2]
    return len(head) == 2 and head[0] == "command" and head[1] in _COMMAND_PROBE_FLAGS


def _pg_write_binary(parts: list[str]) -> str | None:
    """The Postgres binary ``parts`` runs to write a cluster, else ``None``.

    Env assignments, process wrappers and runners (``sudo``, ``xargs``)
    are stripped first (GH-1732, GH-1774). Runners that take the command
    as an argument (``ssh``, ``su -c``, ``docker exec`` …) hand it over
    as its own unit through ``command_units``.
    """
    if _is_command_probe(parts=parts):
        return None
    parts = strip_command_wrappers(parts=parts)
    if not parts:
        return None
    binary = Path(parts[0]).name
    if binary in _PG_WRITE_BINARIES:
        return binary
    if binary == _PG_RESTORE and _pg_restore_targets_database(parts[1:]):
        return binary
    return None


def _pg_write_binaries_in(*, unit: str, budget: _WalkBudget) -> Iterator[str]:
    """Every Postgres write binary ``unit`` runs.

    A unit that cannot be tokenized fails closed on a command-position
    match rather than being skipped. An assigned value already judged is
    not expanded again (GH-2005), so `A=b=b=…` stays linear.
    """
    seen: set[str] = set()
    pending: list[tuple[str, int]] = [(unit, 0)]
    while pending:
        text, depth = pending.pop()
        if text in seen:
            continue
        seen.add(text)
        budget.charge(text=text, depth=depth)
        try:
            segments = command_segments(command=text)
        except UntokenizableCommandError:
            _cap_fallback(text=text)
            match = _PG_COMMAND_POSITION_RE.search(text)
            if match:
                # The match may open on the quote of a runner's command string.
                yield Path(match.group(0).split()[-1].lstrip("'\"")).name
            continue
        for segment in segments:
            parts = list(segment.argv)
            binary = _pg_write_binary(parts)
            if binary:
                yield binary
            # `GIT_PAGER='dropdb prod' git -p log` runs the assigned value.
            pending.extend((value, depth + 1) for value in _assigned_programs(parts=parts))


class _WordRule(Protocol):
    def __call__(self, *, command: str) -> bool: ...


def _direct_psql_verdict(*, command: str, word_rule: _WordRule) -> HookResult | None:
    """The command-position walk, with ``word_rule`` judging each unit too.

    Production passes :func:`_psql_word_anywhere`; the corpus comparison
    (GH-2005) passes a rule that never fires, to see the walk on its own.
    A command past an expansion cap is blocked, never allowed.
    """
    try:
        return _walk_verdict(command=command, word_rule=word_rule, budget=_WalkBudget())
    except _TooComplexError:
        return HookResult(message=TOO_COMPLEX_MSG)


def _walk_verdict(*, command: str, word_rule: _WordRule, budget: _WalkBudget) -> HookResult | None:
    if not (
        _PSQL_PROBE.found_in(command=command)
        or _KEYSTROKE_RUNNER_PROBE.found_in(command=command)
        or _SUBSTITUTED_VALUE_RE.search(command)
        or _runs_substitution(command=command)
    ):
        return None
    segmented: dict[str, list[tuple[str, ...]]] = {}
    for unit in _psql_units(command=command, budget=budget):
        if unit.segments is not None:
            segmented.setdefault(unit.text, [segment.argv for segment in unit.segments])
        if _spells_psql(unit=unit) or (unit.text != command and word_rule(command=unit.text)):
            return HookResult(message=DIRECT_PSQL_MSG)
        if unit.segments is None:
            _cap_fallback(text=unit.text)
            if _PSQL_COMMAND_POSITION_RE.search(unit.text):
                return HookResult(message=DIRECT_PSQL_MSG)
            if _hides_a_program(text=unit.text):
                return HookResult(message=UNTOKENIZABLE_RUNNER_MSG)
            continue
        for segment in unit.segments:
            parts = list(segment.argv)
            if _is_exempt_psql_wrapper(parts):
                wrapped = _check_wrapped_psql_writes(parts=parts)
                if wrapped:
                    return wrapped
                continue
            if _runs_psql(parts):
                return HookResult(message=DIRECT_PSQL_MSG)
    # Keystrokes typed from several units (`tmux send-keys ps; eval
    # "tmux send-keys ql Enter"`) are replayed across them (GH-2001).
    for stream in typed_streams(units=list(segmented.values())):
        stream_unit = _PsqlUnit(text=stream.command, segments=None, opaque=stream.opaque)
        if _spells_psql(unit=stream_unit):
            return HookResult(message=DIRECT_PSQL_MSG)
        result = _walk_verdict(command=stream.command, word_rule=word_rule, budget=budget)
        if result:
            return result
    if word_rule(command=command):
        return HookResult(message=DIRECT_PSQL_MSG)
    return None


def _unit_segments(*, units: Iterable[str]) -> list[tuple[CommandSegment, ...]]:
    segmented: list[tuple[CommandSegment, ...]] = []
    for unit in units:
        try:
            segmented.append(command_segments(command=unit))
        except UntokenizableCommandError:
            continue
    return segmented


@dataclass
class SqlSafetyValidator(ValidatorBase):
    name: ClassVar[str] = "sql-safety"
    rule_id: ClassVar[str] = "DX004"
    profile: ClassVar[ProfileTier] = ProfileTier.MINIMAL

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        return (
            "db.sh" in cmd
            or "psql" in cmd
            or _PSQL_PROBE.found_in(command=cmd)
            or "psycopg2" in cmd
            or "postgres://" in cmd
            or "postgresql://" in cmd
            or _BQ_PROBE.found_in(command=cmd)
            or _PG_BINARY_PROBE.found_in(command=cmd)
            or _KEYSTROKE_RUNNER_PROBE.found_in(command=cmd)
            or bool(_SUBSTITUTED_VALUE_RE.search(cmd))
            or _runs_substitution(command=cmd)
        )

    def validate(self, inp: HookInput) -> HookResult | None:
        command = inp.command

        result = self._check_direct_connection(command=command)
        if result:
            return result

        result = self._check_pg_write_binaries(command=command)
        if result:
            return result

        result = self._check_script_content(command=command)
        if result:
            return result

        result = self._check_direct_psql(command=command)
        if result:
            return result

        result = self._check_bq(command=command)
        if result:
            return result

        return self._check_sql_content(command=command)

    def _check_pg_write_binaries(self, *, command: str) -> HookResult | None:
        # should_run also admits psql/bq/db.sh commands; only one naming a
        # Postgres binary pays for the substitution scan and the lexer.
        if not (
            _PG_BINARY_PROBE.found_in(command=command)
            or _KEYSTROKE_RUNNER_PROBE.found_in(command=command)
        ):
            return None
        units = command_units(command=command)
        # Keystrokes typed from several units (`eval 'tmux send-keys dr';
        # tmux send-keys opdb …`) are replayed across them too (GH-2001).
        streams = typed_streams(
            units=[
                [segment.argv for segment in segments] for segments in _unit_segments(units=units)
            ]
        )
        budget = _WalkBudget()
        try:
            binary = next(
                (
                    binary
                    for unit in (*units, *(stream.command for stream in streams))
                    for binary in _pg_write_binaries_in(unit=unit, budget=budget)
                ),
                None,
            )
        except _TooComplexError:
            return HookResult(message=TOO_COMPLEX_MSG)
        if binary is None:
            return None
        return HookResult(message=PG_WRITE_BINARY_MSG.format(binary=binary))

    def _check_bq(self, *, command: str) -> HookResult | None:
        """Judge every ``bq query`` the command runs, chained or nested (GH-1773).

        A unit the segmenter cannot tokenize fails closed when it names
        ``bq … query`` in command position; skipping it was the evasion.
        """
        if not _BQ_PROBE.found_in(command=command):
            return None
        if _BQ_RC_ENV in command:
            return HookResult(message=_bq_write_message(detail=BQ_FLAG_FILE_DETAIL))
        try:
            units = _bq_units(command=command)
        except _TooComplexError:
            return HookResult(message=TOO_COMPLEX_MSG)
        for unit, opaque in units:
            result = self._check_bq_unit(unit=unit, opaque=opaque)
            if result:
                return result
        return None

    def _check_bq_unit(self, *, unit: str, opaque: bool) -> HookResult | None:
        if opaque:
            result = _bq_letters_verdict(text=unit, pattern=_BQ_WORD_RE)
            if result:
                return result
        try:
            segments = command_segments(command=unit)
        except UntokenizableCommandError:
            if len(unit) > _MAX_FALLBACK_CHARS:
                return HookResult(message=TOO_COMPLEX_MSG)
            result = _bq_letters_verdict(text=unit, pattern=_BQ_POSITION_RE)
            if result:
                return result
            if _BQ_QUERY_POSITION_RE.search(unit):
                return HookResult(message=_bq_write_message(detail=BQ_UNTOKENIZABLE_DETAIL))
            return None
        for segment in segments:
            result = _check_bq_segment(parts=list(segment.argv))
            if result:
                return result
        return None

    def _check_direct_connection(self, *, command: str) -> HookResult | None:
        if "psycopg2" in command or (
            POSTGRES_CONN_RE.search(command) and not any(_is_db_sh(p) for p in command.split())
        ):
            return HookResult(message=DIRECT_CONN_MSG)
        return None

    def _check_script_content(self, *, command: str) -> HookResult | None:
        script_match = re.search(r"(?:uv run(?:\s+--script)?|python3?)\s+(\S+\.py)", command)
        if not script_match:
            return None
        script_path = script_match.group(1)
        try:
            with open(script_path) as fh:
                script_content = fh.read()
            if "psycopg2" in script_content or POSTGRES_CONN_RE.search(script_content):
                return HookResult(
                    message=(
                        f"BLOCKED: {script_path} contains direct database access "
                        "(psycopg2 or postgres:// URL).\n"
                        "Database writes are NEVER permitted. For read-only queries use "
                        f"{DB_SH_PATH}.\n"
                        "If database writes are needed, provide the SQL to the user "
                        "to run manually."
                    )
                )
        except OSError:
            pass
        return None

    def _check_direct_psql(self, *, command: str) -> HookResult | None:
        """Block psql in command position, past wrappers and runners (GH-1809).

        Two layers, each only adding blocks: the command-position walk
        sees psql that runners, substitutions and chains launch, and the
        word rule (:func:`_psql_word_anywhere`) still blocks any bare
        ``psql`` word outside a plain text-tool segment (``rg psql src``,
        ``echo psql``). An untokenizable unit fails closed on a
        command-position match.
        """
        return _direct_psql_verdict(command=command, word_rule=_psql_word_anywhere)

    def _check_sql_content(self, *, command: str) -> HookResult | None:
        sql = _extract_sql_from_command(command)
        if sql is None:
            return None

        result = _validate_sql(sql)
        if not isinstance(result, ErrorResult):
            return None

        return HookResult(
            message=(
                f"BLOCKED by db safety hook: {result.error}\n\n"
                "This query modifies data and cannot be run through the "
                "read-only tool. Print the SQL for the user to run manually."
            )
        )
