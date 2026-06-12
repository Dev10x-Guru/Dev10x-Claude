"""Prompt-time permission-rule shape generalization (GH-597).

When a command prompts, the Claude Code harness suggests a rule shape
that is wrong in one of three directions:

- **over-narrow** — pinned to session-specific args
  (``persist.sh <session-id> *``), so the accepted rule is
  dead-on-arrival next session.
- **over-broad** — a verb-blind prefix whose ``*`` silently grants
  destructive subcommands (``ip route *`` also allows ``ip route
  del``).
- **too-literal** — a bare exact string with no wildcard
  (``yarn build:x``), so any argument variation re-prompts.

``merge_worktree_permissions.generalize_permission`` already fixes the
over-narrow direction, but only *post-hoc* during worktree merge —
never at prompt time. :func:`generalize_rule_shape` is the prompt-time
entry point ``diag-friction`` surfaces so the rule a user accepts is
reusable and safe instead of dead-on-arrival or over-granting.
"""

from __future__ import annotations

import re

from dev10x.skills.permission.merge_worktree_permissions import generalize_permission

_BASH_RULE_RE = re.compile(r"^Bash\((?P<inner>.*)\)$")

# Over-broad: verb-blind command prefixes whose bare ``*`` grants
# destructive subcommands. Narrow each to the safe read subcommand the
# agent actually needs (GH-597, GH-488 evidence #2/#11/#17).
_OVERBROAD_PREFIXES: dict[str, str] = {
    "ip route": "ip route get",
    "ip addr": "ip addr show",
    "ip link": "ip link show",
    "ip neigh": "ip neigh show",
    "systemctl": "systemctl status",
    "docker": "docker ps",
    "kubectl": "kubectl get",
}

# Over-narrow: a wrapper script (``*.sh`` / ``*.py``) pinned to a single
# session-specific positional argument (a session id, ticket id, hash, or
# path), optionally followed by a wildcard. Strip the arg to ``script:*``.
_OVERNARROW_RE = re.compile(r"(?P<script>\S+\.(?:sh|py))\s+\S+(?:\s+\*)?\s*")


def _split_rule(rule: str) -> tuple[str, str]:
    """Return ``("Bash", inner)`` for a ``Bash(...)`` rule, else ``("", rule)``."""
    match = _BASH_RULE_RE.match(rule)
    if match:
        return "Bash", match.group("inner")
    return "", rule


def _rewrap(prefix: str, inner: str) -> str:
    return f"{prefix}({inner})" if prefix else inner


def _narrow_overbroad(inner: str) -> str | None:
    """If ``inner`` is a verb-blind prefix with a bare wildcard, narrow it."""
    stripped = inner.rstrip()
    for prefix, safe in _OVERBROAD_PREFIXES.items():
        # Match "<prefix> *" or "<prefix>:*" — a wildcard with no subcommand.
        if re.fullmatch(rf"{re.escape(prefix)}\s*[:*]\s*\*?", stripped) or stripped in (
            f"{prefix} *",
            f"{prefix}:*",
        ):
            return f"{safe}:*"
    return None


def _strip_session_args(inner: str) -> str | None:
    """If ``inner`` is a wrapper script pinned to one session arg, strip it."""
    match = _OVERNARROW_RE.fullmatch(inner.strip())
    if match:
        return f"{match.group('script')}:*"
    return None


def _add_wildcard(inner: str) -> str:
    """Add a ``:*`` wildcard to a too-literal, wildcard-free rule body."""
    if "*" in inner:
        return inner
    # ``yarn build:x`` → ``yarn build:*``; ``some-tool`` → ``some-tool:*``.
    if ":" in inner:
        head, _, _tail = inner.rpartition(":")
        return f"{head}:*"
    return f"{inner}:*"


def generalize_rule_shape(rule: str) -> str:
    """Generalize a harness-suggested permission rule to a safe, reusable shape.

    Resolves the three failure modes in precedence order: over-broad
    narrowing first (safety), then over-narrow session-arg stripping
    (reuse), then too-literal wildcard addition (reuse). Returns the rule
    unchanged when it is already well-shaped.
    """
    prefix, inner = _split_rule(rule)

    # Only Bash command rules are generalized. A bare shell command (no
    # wrapper) is accepted, but structured rule types — ``mcp__*`` tool
    # grants, ``WebFetch(...)``, ``Read(...)``, etc. — pass through
    # untouched.
    if prefix != "Bash" and (rule.startswith("mcp__") or re.match(r"^[A-Za-z]+\(", rule)):
        return rule

    narrowed = _narrow_overbroad(inner)
    if narrowed is not None:
        return _rewrap(prefix, narrowed)

    # Over-narrow (generic): a wrapper script pinned to one session arg.
    stripped = _strip_session_args(inner)
    if stripped is not None:
        return _rewrap(prefix, stripped)

    # Over-narrow (known patterns): reuse the post-hoc generalizer on the
    # unwrapped inner (its greedy patterns would otherwise eat the closing
    # ``)`` of a ``Bash(...)`` rule). It strips ticket ids / hashes / tmp
    # paths for named scripts and git ops.
    generalized_inner = generalize_permission(inner)
    if generalized_inner != inner:
        return _rewrap(prefix, _add_wildcard(generalized_inner))

    # Too-literal: a wildcard-free bare exact string re-prompts on any
    # argument change — add ``:*``.
    return _rewrap(prefix, _add_wildcard(inner))
