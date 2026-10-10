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
linter being run (GH-1133). See :func:`_command_segments`.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import ENV_VAR_RE
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


# Shell operators that end one command and begin another. Segmenting on
# these is what lets the validator anchor on an *invocation* rather than a
# mention: everything after a separator is a new argv, everything else is an
# argument to the current one.
_SEGMENT_SEPARATORS = frozenset({"|", "||", "&&", ";", "&"})

# Tokens that may open a segment without being the program it runs.
_SHELL_KEYWORDS = frozenset(
    {"do", "then", "else", "elif", "{", "}", "(", ")", "!", "time", "exec", "command"}
)


def _command_segments(command: str) -> list[list[str]]:
    """Split ``command`` into argv segments, respecting shell quoting.

    Raises ``ValueError`` on an unterminated quote, like ``shlex.split``.

    A quote-aware lexer is load-bearing, not a tidy-up (GH-1133). The
    previous ``command.split("|")`` was blind to quoting, so the pipes inside
    a search pattern — ``rg -n "pre-commit|ruff|mypy" settings.json`` — split
    the command into three fragments, the middle one being the bare token
    ``ruff``. That fragment is indistinguishable from a real bare invocation,
    so a read-only search was denied with a ``pre-commit run --files`` hint
    that cannot apply to a search. Lexing first keeps the pattern a single
    token. It also segments on ``&&``/``;``/``||``, which the raw split never
    saw, so a linter chained behind another command is caught rather than
    hidden behind the leading executable.

    Note the scope change this brings: an unterminated quote now
    abandons the WHOLE command rather than the one ``|``-fragment the
    old split would skip, so ``rg "a | ruff check .`` is no longer
    blocked on its second fragment. That is deliberate — an unparseable
    command offers no invocation to anchor on, and bash rejects it
    anyway.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in _SEGMENT_SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _strip_env_prefix(parts: list[str]) -> list[str]:
    i = 0
    while i < len(parts) and ENV_VAR_RE.match(parts[i]):
        i += 1
    return parts[i:]


def _strip_runner(parts: list[str]) -> list[str]:
    """Strip a leading runner sequence (``uv run``, ``npx``, …) once."""
    for sequence in _RUNNER_SEQUENCES:
        if tuple(parts[: len(sequence)]) == sequence:
            return parts[len(sequence) :]
    return parts


def _strip_keywords(parts: list[str]) -> list[str]:
    """Drop leading shell keywords so the real executable surfaces.

    Segmenting on `;` and `&&` newly produces segments that OPEN with a
    keyword — `for f in *.py; do ruff check $f; done` yields a `do ruff
    check $f` segment whose first token is `do`, not `ruff`. Without
    this the loop body reads as a `do` invocation and the linter inside
    it is missed, which would turn a false-positive fix into a false
    negative — strictly the worse defect.
    """
    index = 0
    while index < len(parts) and parts[index] in _SHELL_KEYWORDS:
        index += 1
    return parts[index:]


def _effective_tool(parts: list[str]) -> str | None:
    """Return the executable after stripping keywords, wrappers and flags."""
    parts = _strip_runner(_strip_keywords(parts))
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
            segments = _command_segments(inp.command)
        except ValueError:
            # Unterminated quote — the command is unparseable, so there is no
            # invocation to anchor on. Do not guess.
            return None
        for segment in segments:
            parts = _strip_env_prefix(segment)
            if not parts:
                continue
            if _is_pm_lint_script(parts):
                return HookResult(message=INLINE_LINTER_MSG)
            if _effective_tool(parts) in LINTER_TOOLS:
                return HookResult(message=INLINE_LINTER_MSG)
        return None
