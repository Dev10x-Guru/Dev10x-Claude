from __future__ import annotations

import re
from typing import Any

from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

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

# BigQuery statements the Postgres denylist does not name. `CALL` runs a
# stored procedure whose body no check can see; EXTERNAL_QUERY runs SQL
# held in a string literal that escapes can disguise. It is matched on
# lexed code, where a comment between two words is already a space.
BQ_BLOCKED_KEYWORDS = re.compile(
    r"\b(MERGE|EXPORT\s+DATA|LOAD\s+DATA|EXECUTE\s+IMMEDIATE|CALL|"
    r"EXTERNAL_QUERY|UNDROP|ASSERT|DECLARE|RAISE)\b",
    re.IGNORECASE,
)

# Characters some SQL lexers treat as line ends. A `#` or `--` comment
# this check ends only at `\n` could hide code behind one, so they are
# refused anywhere rather than guessed at.
_AMBIGUOUS_BREAKS_RE = re.compile(r"[\r\f\v\x1c-\x1e\x85  ]")
# GoogleSQL may close a triple-quoted literal at the LAST quote of a run
# where this lexer closes at the first; a run of four or more makes the
# two readings differ, so it is refused rather than guessed.
_QUOTE_RUN_RE = re.compile(r"'{4,}|\"{4,}")
MAX_STATEMENT_CHARS = 64 * 1024
_SELECT_PREFIX_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_RAW_PREFIX_RE = re.compile(r"(?:^|[^\w])(?:[rR]|[rR][bB]|[bB][rR])$")

# `bq` commands that change nothing. Every other verb (`rm`, `load`, `cp`,
# `mk`, `update`, `insert`, `extract`, `truncate`, `undelete`, `cancel`,
# `init`, `shell`, `partition`, the IAM writers, and any verb added later)
# is refused.
BQ_READ_ONLY_VERBS = frozenset(
    {"ls", "show", "head", "query", "version", "help", "info", "wait", "get-iam-policy"}
)

_SINGLE_QUOTED_RE = re.compile(r"'[^']*'")


def validate_read_only_sql(sql: str) -> Result[dict[str, Any]]:
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


def _quote_at(*, sql: str, start: int) -> str:
    char = sql[start]
    if char != "`" and sql.startswith(char * 3, start):
        return char * 3
    return char


def _literal_end(*, sql: str, start: int, quote: str) -> int | None:
    index = start + len(quote)
    while index < len(sql):
        if sql[index] == "\\":
            index += 2
            continue
        if sql.startswith(quote, index):
            return index + len(quote)
        index += 1
    return None


def code_only(sql: str) -> Result[str]:
    """``sql`` with comments as spaces and every quoted token as ``_q_``.

    A regex that strips only single-quoted strings lets a quote inside a
    double-quoted string swallow real code, ``;`` separators included.
    This lexer knows every GoogleSQL quote and comment form, and refuses
    what it cannot read rather than guessing.
    """
    out: list[str] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "#" or sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = len(sql) if newline == -1 else newline
            out.append(" ")
        elif sql.startswith("/*", index):
            close = sql.find("*/", index + 2)
            if close == -1:
                return err("Unterminated /* comment.")
            index = close + 2
            out.append(" ")
        elif char in "'\"`":
            if char != "`" and _RAW_PREFIX_RE.search(sql[max(0, index - 3) : index]):
                return err("Raw string literals (r'…') are not accepted; drop the r prefix.")
            quote = _quote_at(sql=sql, start=index)
            end = _literal_end(sql=sql, start=index, quote=quote)
            if end is None:
                return err(f"Unterminated {quote} literal.")
            index = end
            out.append(" _q_ ")
        else:
            out.append(char)
            index += 1
    return ok("".join(out))


def _blocked_keyword(*, code: str) -> ErrorResult | None:
    for pattern in (BLOCKED_KEYWORDS, BQ_BLOCKED_KEYWORDS):
        match = pattern.search(code)
        if match:
            keyword = " ".join(match.group(0).upper().split())
            return err(f"Query contains blocked keyword: {keyword}")
    return None


def validate_bigquery_statement(sql: str) -> Result[str]:
    """Prove ``sql`` is one GoogleSQL SELECT/WITH statement, or refuse it.

    Returns the code-only text. Any ``;`` left after lexing, trailing or
    not, is refused, so a second statement can never ride along whatever
    its keyword. Keywords are matched on the lexed code, and the BigQuery
    ones on the raw text too, as develop's DX004 did: a MERGE or CALL
    inside a literal or comment is refused (fail closed over the false
    positive). Both patterns use a plain \\s+ gap, so the scan is linear.
    """
    if len(sql) > MAX_STATEMENT_CHARS:
        return err(f"SQL is longer than {MAX_STATEMENT_CHARS} characters.")
    if _AMBIGUOUS_BREAKS_RE.search(sql):
        return err(r"SQL contains \r, \f, \v or another ambiguous line break; use \n only.")
    if _QUOTE_RUN_RE.search(sql):
        return err("SQL contains a run of four or more identical quotes, which reads ambiguously.")
    raw_match = BQ_BLOCKED_KEYWORDS.search(sql)
    if raw_match:
        keyword = " ".join(raw_match.group(0).upper().split())
        return err(f"Query contains blocked keyword: {keyword}")
    lexed = code_only(sql)
    if isinstance(lexed, ErrorResult):
        return lexed
    code = " ".join(lexed.value.split())
    if ";" in code:
        return err("Multi-statement SQL is not allowed; submit one statement without ';'.")
    if not _SELECT_PREFIX_RE.match(code):
        return err("Query does not start with SELECT/WITH.\nOnly read-only queries are allowed.")
    blocked = _blocked_keyword(code=code)
    if blocked:
        return blocked
    return ok(code)


def validate_bigquery_sql(sql: str) -> Result[dict[str, Any]]:
    """The DX004 contract for `bq query`: the Postgres-shaped rules on the
    raw text, then the GoogleSQL statement check. Each only adds refusals."""
    result = validate_read_only_sql(sql)
    if isinstance(result, ErrorResult):
        return result
    statement = validate_bigquery_statement(sql)
    if isinstance(statement, ErrorResult):
        return statement
    return ok({})
