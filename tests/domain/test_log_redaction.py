"""Tests for dev10x.domain.log_redaction (GH-1639)."""

from __future__ import annotations

import pytest
from dev10x.domain.log_redaction import (
    REDACTED,
    is_sensitive_field,
    redact_fields,
    redact_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("GITHUB_TOKEN=ghx123abc rest", f"GITHUB_TOKEN={REDACTED} rest"),
        ("db_password=hunter2", f"db_password={REDACTED}"),
        (
            "postgres://app:s3cret@db.internal:5432/x",
            f"postgres://{REDACTED}@db.internal:5432/x",
        ),
        ("Authorization: Bearer abcdefgh12345678", f"Authorization: Bearer {REDACTED}"),
        ("token ghp_" + "a" * 36, f"token {REDACTED}"),
        ("key xoxb-1234567890-abcdef", f"key {REDACTED}"),
        ("aws AKIAABCDEFGHIJKLMNOP id", f"aws {REDACTED} id"),
        ("password=hunter2", f"password={REDACTED}"),
        ("login TOKEN=abc ok", f"login TOKEN={REDACTED} ok"),
        ("run --token=abc", f"run --token={REDACTED}"),
        ("api_key=abc", f"api_key={REDACTED}"),
        ("password: hunter2", f"password: {REDACTED}"),
        ('{"password": "x y"}', f'{{"password": {REDACTED}}}'),
        ('password="a b" next', f"password={REDACTED} next"),
        ("psql --password hunter2 -h db", f"psql --password {REDACTED} -h db"),
        ("AUTHORIZATION=abc", f"AUTHORIZATION={REDACTED}"),
        ("Authorization: Basic dXNlcjpwYXNz", f"Authorization: Basic {REDACTED}"),
    ],
)
def test_redact_text_masks_secret_values(text: str, expected: str) -> None:
    assert redact_text(text=text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "git push origin janusz/hook-m1-followups",
        "https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1639",
        "token count: 12",
        "PAGE_SIZE=50",
        "token validation failed",
        "password reset requested",
    ],
)
def test_redact_text_leaves_ordinary_text_alone(text: str) -> None:
    assert redact_text(text=text) == text


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("api_key", True),
        ("GITHUB_TOKEN", True),
        ("password", True),
        ("Authorization", True),
        ("credentials", True),
        ("pr_number", False),
        ("repo", False),
    ],
)
def test_is_sensitive_field(name: str, expected: bool) -> None:
    assert is_sensitive_field(name=name) is expected


def test_redact_fields_stringifies_and_masks_non_json_values() -> None:
    fields = {
        "error": RuntimeError("connect failed for postgres://u:pw@db/x"),
        "flags": {"--token=abc"},
        "count": 3,
        "ok": True,
        "missing": None,
    }

    assert redact_fields(fields=fields) == {
        "error": f"connect failed for postgres://{REDACTED}@db/x",
        "flags": [f"--token={REDACTED}"],
        "count": 3,
        "ok": True,
        "missing": None,
    }


def test_redact_fields_masks_by_name_and_recurses_by_value() -> None:
    fields = {
        "token": "anything",
        "pr_number": 7,
        "nested": {"secret": "x", "url": "https://u:p@host/"},
        "argv": ["deploy", "API_TOKEN=abc"],
    }

    assert redact_fields(fields=fields) == {
        "token": REDACTED,
        "pr_number": 7,
        "nested": {"secret": REDACTED, "url": f"https://{REDACTED}@host/"},
        "argv": ["deploy", f"API_TOKEN={REDACTED}"],
    }
