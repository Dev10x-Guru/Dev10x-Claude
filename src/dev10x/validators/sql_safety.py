"""Validator: read-only SQL enforcement.

Ported from validate-sql.py.

Validates that db.sh / psql commands contain only read-only SQL.
Blocks direct psycopg2 / postgres:// connections.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from dev10x.domain import HookInput, HookResult
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
        str(Path(__file__).resolve().parents[3]),
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
        )

    def validate(self, inp: HookInput) -> HookResult | None:
        command = inp.command

        result = self._check_direct_connection(command=command)
        if result:
            return result

        result = self._check_script_content(command=command)
        if result:
            return result

        result = self._check_direct_psql(command=command)
        if result:
            return result

        return self._check_sql_content(command=command)

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
