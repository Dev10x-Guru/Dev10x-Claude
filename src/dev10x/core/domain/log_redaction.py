"""Redact secrets from diagnostic log records before they are written (GH-1639).

Tool payloads reach the diagnostic log through ordinary ``logging`` calls,
so redaction has to sit at the sink rather than at each call site: a call
site that forgets is the one that leaks. This module is the pure half — it
knows what a secret looks like, never where a record goes.

Two shapes are covered. A structured field is redacted by its NAME:
the identifier vocabulary MCP promotion and permission grant share
(``sensitivity.name_is_sensitive``), plus a credential word found
anywhere in the name. "Anywhere" over-redacts on purpose — ``max_tokens``
is masked too — because a missed secret costs more than a lost count.
Free text is redacted by VALUE shape: ``key=value``, ``key: value`` and
``--key value`` where the key holds one of those credential words, URL
userinfo, Bearer/Basic credentials, and well-known token prefixes.
"""

from __future__ import annotations

import re
from typing import Any

from dev10x.domain.sensitivity import name_is_sensitive

REDACTED = "[REDACTED]"

_CREDENTIAL_WORD = (
    r"(?:password|passwd|token|secret|api[_-]?key|private[_-]?key|authorization|cookie)"
)

# Field names holding a credential word anywhere, even when no word
# token stands alone in them (`api_key`, `GITHUB_TOKEN`, `db_password`).
# Also the cheap gate for the key/value passes below: no credential word,
# nothing for them to match.
_CREDENTIAL_NAME_RE = re.compile(_CREDENTIAL_WORD, re.IGNORECASE)

_CREDENTIAL_KEY = rf"[A-Za-z0-9_.-]*{_CREDENTIAL_WORD}[A-Za-z0-9_.-]*"
_VALUE = r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"

# `key=value`, `key: value`, `"key": "value"` — the key may be the bare
# credential word itself. An auth scheme after the separator is left to
# _AUTH_SCHEME_RE, so the scheme word survives and the credential goes.
_KEY_VALUE_RE = re.compile(
    rf"(?<![A-Za-z0-9_])([\"']?{_CREDENTIAL_KEY}[\"']?\s*[:=]\s*)"
    rf"(?!(?:Bearer|Basic)\s){_VALUE}",
    re.IGNORECASE,
)
# `--password hunter2`: a credential-named flag followed by its value.
_FLAG_VALUE_RE = re.compile(rf"(--?{_CREDENTIAL_KEY}\s+)(?!-){_VALUE}", re.IGNORECASE)
_AUTH_SCHEME_RE = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_URL_USERINFO_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
_TOKEN_PREFIX_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})"
)


def is_sensitive_field(*, name: str) -> bool:
    return name_is_sensitive(name=name) or _CREDENTIAL_NAME_RE.search(name) is not None


def redact_text(*, text: str) -> str:
    text = _AUTH_SCHEME_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _URL_USERINFO_RE.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    if _CREDENTIAL_NAME_RE.search(text):
        text = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
        text = _FLAG_VALUE_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _TOKEN_PREFIX_RE.sub(REDACTED, text)


def redact_value(*, value: Any) -> Any:
    """Redact ``value`` into a JSON-native shape.

    Anything that is not a JSON scalar or container is stringified HERE,
    so the sink's ``json.dumps(default=str)`` never meets an object whose
    ``__str__`` carries a secret past redaction.
    """
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict):
        return redact_fields(fields=value)
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(value=item) for item in value]
    return redact_text(text=value if isinstance(value, str) else str(value))


def redact_fields(*, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: REDACTED if is_sensitive_field(name=str(key)) else redact_value(value=value)
        for key, value in fields.items()
    }
