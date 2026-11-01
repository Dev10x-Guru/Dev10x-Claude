"""Validator: read-only SQL enforcement.

Ported from validate-sql.py.

Validates that db.sh / psql commands contain only read-only SQL.
Blocks direct psycopg2 / postgres:// connections.

``bq query`` gets the same read-only contract (GH-1633): a blanket
``Bash(bq query:*)`` allow auto-approved ``DELETE``/``MERGE`` against
BigQuery while every Postgres path was guarded. This closes that hole at
the hook; a schema-first ``bq`` wrapper skill, after which the raw
command moves to deny, is the remaining scope on GH-1633.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import (
    ANY_CASE_ENV_VAR_RE,
    command_units,
    strip_command_wrappers,
)
from dev10x.domain.common.result import ErrorResult, Result, err, ok
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

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
DB_SH_PATH = _PLUGIN_ROOT / "skills" / "db-psql" / "scripts" / "db.sh"

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

_COMMAND_SEPARATORS = frozenset({"&&", "||", ";"})

# shlex keeps redirections as ordinary tokens, so `bq query < q.sql`
# would otherwise read the filename as query text. A spaced operator
# consumes the next token; an attached one (`<q.sql`, `2>/dev/null`) is
# a single token.
_REDIRECT_OPERATORS = frozenset({"<", "<<", "<<<", ">", ">>", "2>", "2>>", "&>"})
_FD_REDIRECT_PREFIXES = frozenset({"1>", "2>", "&>"})

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


def _simple_commands(*, command: str) -> list[list[str]]:
    """Token lists for each simple command in ``command``.

    Splits on pipes (quote-aware) and on spaced ``&&``/``||``/``;``
    tokens, so ``cd x && bq query …`` still exposes the ``bq`` call.
    An unparseable segment yields nothing; the other validators on
    the chain judge it.
    """
    commands: list[list[str]] = []
    for segment in _split_pipe_segments(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        current: list[str] = []
        for token in tokens:
            if token in _COMMAND_SEPARATORS:
                commands.append(current)
                current = []
                continue
            current.append(token)
        commands.append(current)
    return [parts for parts in commands if parts]


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
    sql_tokens: list[str] = []
    remaining = iter(args)
    for token in remaining:
        flag = _bq_flag_name(token)
        if flag in _BQ_WRITE_FLAGS:
            return HookResult(message=_bq_write_message(detail=f"{flag} writes a table."))
        takes_next_value = "=" not in token and flag in _BQ_VALUE_FLAGS
        if takes_next_value or token in _REDIRECT_OPERATORS:
            next(remaining, None)
            continue
        if token.startswith(("-", "<", ">")) or token[:2] in _FD_REDIRECT_PREFIXES:
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


_BQ_WORD_RE = re.compile(r"\bbq\b")

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
_PG_BINARY_RE = re.compile(r"\b(?:" + "|".join(sorted(_PG_BINARIES)) + r")\b")

# The fast path must see the word the shell will run: `d""ropdb` and
# `dr\opdb` tokenize to `dropdb` while the raw text does not contain it.
_DROP_SHELL_QUOTING = str.maketrans("", "", "\"'\\")

# Tokens that end one command and start the next. `_simple_commands`
# only splits on spaced `&&`/`||`/`;`, which let `x;dropdb`, `x & dropdb`
# and `(dropdb x)` through (GH-1732 review); the binary check splits on
# every operator a shell does. The bq check stays on `_simple_commands`
# on purpose: moving it changes BigQuery behaviour, which is GH-1633's.
_PG_SEGMENT_BREAKS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")"})
_PG_LEADING_KEYWORDS = frozenset(
    {"{", "}", "!", "if", "then", "else", "elif", "while", "until", "do"}
)

# Fail-closed fallback when a unit cannot be tokenized: a write binary in
# command position, optionally behind env assignments or a path.
_PG_COMMAND_POSITION_RE = re.compile(
    r"(?:^|[|;&(\n{])\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:[\w./~-]*/)?"
    r"(?:" + "|".join(sorted(_PG_WRITE_BINARIES)) + r")\b"
)

# Commands that run another command named somewhere in their arguments
# (GH-1732 review). `sudo -u postgres dropdb` is the standard admin
# idiom. Kept local rather than taught to strip_command_wrappers, which
# would change DX003 and DX016 too. `docker exec` / `op run` were the
# psql-read exemptions and are covered here too.
_PG_RUNNERS = frozenset(
    {"sudo", "doas", "su", "xargs", "ssh", "kubectl", "docker", "podman", "op", "find"}
)

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


def _mentions_pg_binary(*, command: str) -> bool:
    return _PG_BINARY_RE.search(command.translate(_DROP_SHELL_QUOTING)) is not None


def _pg_segments(*, unit: str) -> list[list[str]]:
    """Argv segments of ``unit``, split on every shell command operator.

    Raises ``ValueError`` when the unit cannot be tokenized.
    """
    lexer = shlex.shlex(unit.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in _PG_SEGMENT_BREAKS:
            segments.append([])
        elif segments[-1] or token not in _PG_LEADING_KEYWORDS:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _is_command_probe(*, parts: list[str]) -> bool:
    head = [token for token in parts if not ANY_CASE_ENV_VAR_RE.match(token)][:2]
    return len(head) == 2 and head[0] == "command" and head[1] in _COMMAND_PROBE_FLAGS


def _runner_target(*, parts: list[str]) -> list[str]:
    """The argv a runner (``sudo``, ``ssh`` …) hands a Postgres binary.

    Words inside a quoted argument count, so ``su postgres -c 'dropdb x'``
    resolves to ``["dropdb", "x"]``. Empty when no binary is named.
    """
    words = [word for token in parts[1:] for word in token.split()]
    start = next(
        (i for i, word in enumerate(words) if Path(word).name in _PG_BINARIES),
        len(words),
    )
    return words[start:]


def _pg_write_binary(parts: list[str]) -> str | None:
    """The Postgres binary ``parts`` runs to write a cluster, else ``None``.

    Env assignments and process wrappers are stripped first (GH-1732), and
    runner commands (``sudo``, ``ssh``, ``xargs``, ``docker exec`` …) are
    looked through: a wrapped ``dropdb`` is still a write.
    """
    if _is_command_probe(parts=parts):
        return None
    parts = strip_command_wrappers(parts=parts)
    if parts and Path(parts[0]).name in _PG_RUNNERS:
        parts = _runner_target(parts=parts)
    if not parts:
        return None
    binary = Path(parts[0]).name
    if binary in _PG_WRITE_BINARIES:
        return binary
    if binary == _PG_RESTORE and _pg_restore_targets_database(parts[1:]):
        return binary
    return None


def _pg_write_binaries_in(*, unit: str) -> Iterator[str]:
    """Every Postgres write binary ``unit`` runs.

    A unit that cannot be tokenized fails closed on a command-position
    match rather than being skipped.
    """
    try:
        segments = _pg_segments(unit=unit)
    except ValueError:
        match = _PG_COMMAND_POSITION_RE.search(unit)
        if match:
            yield Path(match.group(0).split()[-1]).name
        return
    for parts in segments:
        binary = _pg_write_binary(parts)
        if binary:
            yield binary


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
            or "psycopg2" in cmd
            or "postgres://" in cmd
            or "postgresql://" in cmd
            or _BQ_WORD_RE.search(cmd) is not None
            or _mentions_pg_binary(command=cmd)
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
        if not _mentions_pg_binary(command=command):
            return None
        binary = next(
            (
                binary
                for unit in command_units(command=command)
                for binary in _pg_write_binaries_in(unit=unit)
            ),
            None,
        )
        if binary is None:
            return None
        return HookResult(message=PG_WRITE_BINARY_MSG.format(binary=binary))

    def _check_bq(self, *, command: str) -> HookResult | None:
        for parts in _simple_commands(command=command):
            args = _bq_query_args(parts)
            if args is None:
                continue
            result = _check_bq_query(args=args)
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
        for seg in _split_pipe_segments(command):
            seg = seg.strip()
            try:
                seg_parts = shlex.split(seg)
            except ValueError:
                seg_parts = []
            if _is_exempt_psql_wrapper(seg_parts):
                wrapped = _check_wrapped_psql_writes(parts=seg_parts)
                if wrapped:
                    return wrapped
                continue
            if any(_is_psql_binary(t) for t in seg_parts):
                return HookResult(message=DIRECT_PSQL_MSG)
        return None

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
