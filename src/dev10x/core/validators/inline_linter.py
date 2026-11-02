"""Validator: block inline linters/formatters; defer to pre-commit (GH-596).

Linting and formatting belong at commit time, through the project's
single pre-commit source of truth — never as friction-generating inline
commands. This validator blocks inline ``ruff``/``black``/``mypy``/
``isort``/``eslint``/``prettier`` invocations in both their **bare**
(``ruff check``) and **wrapped** (``uv run ruff``, ``npx eslint``,
``pnpm lint``, ``python -m ruff``) forms, steering to ``pre-commit run``.

D14 (GH-488) resolved to a **global** block — the rule applies in all
repos, including Dev10x's own. Everyone lints through pre-commit.

The block fires on an **invocation**, never on a mention: a linter name
appearing as a search pattern, a ``--grep`` argument, or a path is not a
linter being run (GH-1133). Segments come from the shared
:func:`~dev10x.domain.common.bash_tokens.command_segments` (GH-1773).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import (
    UntokenizableCommandError,
    command_segments,
    strip_command_wrappers,
)
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

# Linter/formatter executables blocked as inline invocations.
LINTER_TOOLS = frozenset({"ruff", "black", "mypy", "isort", "eslint", "prettier"})

# JS package managers whose ``lint`` script is an inline-lint invocation.
_JS_PACKAGE_MANAGERS = frozenset({"pnpm", "yarn", "npm"})

# ``lint:``-prefixed scripts that run a TYPE CHECKER, not a linter (GH-1025).
# `lint:tsc` conventionally runs only `tsc`, so there is no inline linter to
# redirect and no pre-commit hook to defer to — blocking it makes the
# documented way to typecheck a workspace unreachable. The exemption is
# script-name-scoped rather than a blanket `lint:*` escape, so siblings like
# `lint:eslint` keep blocking.
_TYPECHECK_SCRIPTS = frozenset({"lint:tsc", "lint:types", "lint:typecheck"})

# Leading token sequences that wrap a tool — stripped to find the
# effective executable (``uv run ruff`` → ``ruff``).
_RUNNER_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("uv", "run"),
    ("uvx",),
    ("npx",),
    ("pnpm", "exec"),
    ("pnpm", "dlx"),
    ("poetry", "run"),
    ("pipx", "run"),
    ("python", "-m"),
    ("python3", "-m"),
    ("yarn",),
)

# Fast skip gate — only run the precise check when a linter name or a
# ``lint`` token could plausibly appear.
_TRIGGER_RE = re.compile(r"\b(ruff|black|mypy|isort|eslint|prettier|lint)\b")

INLINE_LINTER_MSG = (
    "\U0001f6ab  Inline linter/formatter blocked (GH-596).\n\n"
    "Don't lint inline — linting runs at commit time via the project's\n"
    "single pre-commit source of truth. If you must run it now, scope it\n"
    "to the changed files:\n\n"
    "  pre-commit run --files <files>\n\n"
    "No .pre-commit-config.yaml yet? Set one up (`pre-commit install` +\n"
    "a config with the project's ruff/mypy hooks) — do NOT fall back to\n"
    "inline ruff/black/mypy/isort/eslint/prettier."
)


def _strip_runner(parts: list[str]) -> list[str]:
    """Strip a leading runner sequence (``uv run``, ``npx``, …) once."""
    for sequence in _RUNNER_SEQUENCES:
        if tuple(parts[: len(sequence)]) == sequence:
            return parts[len(sequence) :]
    return parts


def _effective_tool(parts: list[str]) -> str | None:
    """Return the executable after stripping runners and flags."""
    parts = _strip_runner(parts)
    rest = [p for p in parts if not p.startswith("-")]
    return rest[0] if rest else None


def _is_pm_lint_script(parts: list[str]) -> bool:
    """True for ``pnpm lint`` / ``yarn lint`` / ``npm run lint[:x]`` shapes.

    Type-check scripts (``lint:tsc`` and friends) are exempt — see
    :data:`_TYPECHECK_SCRIPTS`.
    """
    if not parts or parts[0] not in _JS_PACKAGE_MANAGERS:
        return False
    if any(token in _TYPECHECK_SCRIPTS for token in parts[1:]):
        return False
    return any(token == "lint" or token.startswith("lint:") for token in parts[1:])


@dataclass
class InlineLinterValidator(ValidatorBase):
    name: ClassVar[str] = "inline-linter"
    rule_id: ClassVar[str] = "DX016"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        return bool(_TRIGGER_RE.search(inp.command))

    def validate(self, inp: HookInput) -> HookResult | None:
        try:
            segments = command_segments(command=inp.command)
        except UntokenizableCommandError:
            # Abstain rather than fail closed: this is a friction rule, an
            # unterminated quote offers no invocation to anchor on, and
            # bash rejects the command anyway (GH-1133).
            return None
        for segment in segments:
            parts = strip_command_wrappers(parts=list(segment.argv))
            if not parts:
                continue
            if _is_pm_lint_script(parts):
                return HookResult(message=INLINE_LINTER_MSG)
            if _effective_tool(parts) in LINTER_TOOLS:
                return HookResult(message=INLINE_LINTER_MSG)
        return None
