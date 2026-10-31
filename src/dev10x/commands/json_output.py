"""Single-channel JSON error output for stdout-parsed commands.

A command whose stdout is parsed emits its error as a JSON object on
stdout too, then exits non-zero (`.claude/rules/script-domain-boundaries.md`).
"""

from __future__ import annotations

import json
import sys
from typing import NoReturn

import click

from dev10x.core.domain.common.result import ErrorResult


def fail_json(*, error: str | ErrorResult) -> NoReturn:
    payload = error.to_dict() if isinstance(error, ErrorResult) else {"error": error}
    click.echo(json.dumps(payload))
    sys.exit(1)
