from __future__ import annotations

import re
from dataclasses import dataclass

SAFE_PREFIX_RE = re.compile(
    r"^(SELECT|WITH|EXPLAIN|SHOW)\b",
    re.IGNORECASE,
)

BLOCKED_KEYWORD_RE = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|"
    r"GRANT|REVOKE|VACUUM|REINDEX|CLUSTER|COPY|"
    r"DO\s*\$|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|"
    r"SET\s+(?!search_path|statement_timeout|default_transaction_read_only)|"
    r"LOCK|DISCARD|RESET|"
    r"COMMENT\s+ON|SECURITY\s+LABEL|REASSIGN|"
    r"REFRESH\s+MATERIALIZED"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SqlStatement:
    raw: str
    prefix: str
    is_read_only: bool

    @classmethod
    def parse(cls, sql: str) -> SqlStatement:
        cleaned = re.sub(r"^\s*(--.*)?", "", sql, flags=re.MULTILINE).strip()
        match = SAFE_PREFIX_RE.match(cleaned)
        prefix = match.group(1).upper() if match else ""
        read_only = bool(match) and not BLOCKED_KEYWORD_RE.search(cleaned)
        return cls(raw=sql, prefix=prefix, is_read_only=read_only)


def is_read_only_sql(sql: str) -> bool:
    return SqlStatement.parse(sql=sql).is_read_only
