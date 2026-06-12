"""Validator: block inline linters/formatters; defer to pre-commit (GH-596).

Linting and formatting belong at commit time, through the project's
single pre-commit source of truth — never as friction-generating inline
commands. This validator blocks inline ``ruff``/``black``/``mypy``/
``isort``/``eslint``/``prettier`` invocations in both their **bare**
(``ruff check``) and **wrapped** (``uv run ruff``, ``npx eslint``,
``pnpm lint``, ``python -m ruff``) forms, steering to ``pre-commit run``.

D14 (GH-488) resolved to a **global** block — the rule applies in all
repos, including Dev10x's own. Everyone lints through pre-commit.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

# Linter/formatter executables blocked as inline invocations.
LINTER_TOOLS = frozenset({"ruff", "black", "mypy", "isort", "eslint", "prettier"})

# JS package managers whose ``lint`` script is an inline-lint invocation.
_JS_PACKAGE_MANAGERS = frozenset({"pnpm", "yarn", "npm"})

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

_ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")

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


def _strip_env_prefix(parts: list[str]) -> list[str]:
    i = 0
    while i < len(parts) and _ENV_VAR_RE.match(parts[i]):
        i += 1
    return parts[i:]


def _strip_runner(parts: list[str]) -> list[str]:
    """Strip a leading runner sequence (``uv run``, ``npx``, …) once."""
    for sequence in _RUNNER_SEQUENCES:
        if tuple(parts[: len(sequence)]) == sequence:
            return parts[len(sequence) :]
    return parts


def _effective_tool(parts: list[str]) -> str | None:
    """Return the executable after stripping runner wrappers and leading flags."""
    parts = _strip_runner(parts)
    rest = [p for p in parts if not p.startswith("-")]
    return rest[0] if rest else None


def _is_pm_lint_script(parts: list[str]) -> bool:
    """True for ``pnpm lint`` / ``yarn lint`` / ``npm run lint[:x]`` shapes."""
    if not parts or parts[0] not in _JS_PACKAGE_MANAGERS:
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
        for segment in inp.command.split("|"):
            try:
                parts = _strip_env_prefix(shlex.split(segment.strip()))
            except ValueError:
                continue
            if not parts:
                continue
            if _is_pm_lint_script(parts):
                return HookResult(message=INLINE_LINTER_MSG)
            if _effective_tool(parts) in LINTER_TOOLS:
                return HookResult(message=INLINE_LINTER_MSG)
        return None
