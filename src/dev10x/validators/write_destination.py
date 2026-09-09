"""Validator: block shell file-writes that land inside the working tree (GH-1245).

``cp``, ``mv``, ``tee``, ``touch`` and ``install`` place file content
without going through the ``Write`` tool, so they never reach
``validate-edit-write.py``. That is an unguarded write path into the
repository, and the cost is not only the skipped validator:

  - file-state tracking never sees the write, so a later ``Edit`` on the
    same path has no baseline;
  - the agent never *reads* what it placed. A ``cp`` cannot discover
    correctness, because copying is not reading. GH-1245 records an
    866-line script copied in sight-unseen; re-done through
    ``Read`` + ``Write`` it was immediately found to be wrong (dead
    ``/tmp`` paths, a duplicated block, useless timing offsets).

Scope is deliberately narrow: only a destination that resolves *inside
the working tree* is denied. A ``/tmp`` → ``/tmp`` copy, a staging move
under a scratch root, or any write outside the checkout is left alone —
those are legitimate shell work and blocking them would be friction with
no safety payoff.

Destination detection follows each verb's own convention rather than a
single positional rule: ``cp``/``mv``/``install`` write their last
operand, ``tee``/``touch`` write every operand, and a ``-t`` /
``--target-directory`` flag inverts both — its value is the destination
and every operand becomes a source.

The working tree is found by walking up from ``HookInput.cwd`` for a
``.git`` entry — a file in a worktree, a directory in a main checkout.
``cwd`` alone will not do: it is the *caller's* current directory (see
``hook_transport``), so a session running from a subdirectory would read
a write to a sibling path inside the same repository as "outside the
tree" and let it through. Walking up costs a handful of ``exists()``
calls and no subprocess, which matters because this validator sits on
the PreToolUse chain and runs on every Bash call under the latency gate
in ``tests/benchmarks/test_startup_time.py``. A ``git rev-parse`` per
Bash call would be the most expensive check in the chain. When ``cwd``
is empty the validator abstains rather than guessing.

Companion to GH-469, which closed the same class of gap for the
``interpreter-guard`` shell-exec bypass.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import split_tokens, substitution_bodies
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

#: Commands whose non-flag arguments name a file they create or overwrite.
#: ``cp``/``mv``/``install`` write their LAST argument; ``tee``/``touch``
#: write EVERY non-flag argument.
_LAST_ARG_WRITERS = frozenset({"cp", "mv", "install"})
_ALL_ARG_WRITERS = frozenset({"tee", "touch"})
_WRITERS = _LAST_ARG_WRITERS | _ALL_ARG_WRITERS

#: Flags whose value IS the destination directory. With one of these the
#: usual positional rule inverts — every operand is a source and the
#: written path is the flag's value, so skipping it the way an unrelated
#: flag value is skipped would miss the write entirely.
_DEST_FLAGS = frozenset({"-t", "--target-directory"})

#: Flags that consume the following token without naming a path, so a
#: value like ``644`` is not mistaken for a destination.
_VALUE_FLAGS = frozenset(
    {
        "-m",
        "--mode",
        "-o",
        "--owner",
        "-g",
        "--group",
        "-S",
        "--suffix",
    }
)

_SEGMENT_SPLIT_RE = re.compile(r"(?:\|\||&&|[|;&\n])")


def _segments(command: str) -> list[str]:
    """Split a command line into pipeline/list segments.

    A writer can sit anywhere in a chain (``foo | tee dest``), so each
    segment is examined on its own rather than only the leading command.

    Command-substitution bodies are flattened in alongside them, for the
    same reason DX003 does it: ``x=$(cp foo dest)`` runs the copy, and a
    splitter that only sees the outer assignment hands back an evasion.
    ``substitution_bodies`` is the shared depth-aware helper DX003 uses,
    so a nested substitution does not truncate its parent.
    """
    units = [command, *substitution_bodies(command, include_backticks=True)]
    return [seg.strip() for unit in units for seg in _SEGMENT_SPLIT_RE.split(unit) if seg.strip()]


def _destinations(*, segment: str) -> tuple[str, list[str]]:
    """The writer verb in ``segment`` and the paths it would write.

    Returns ``("", [])`` when the segment writes nothing, so a caller
    never has to re-tokenize to recover the verb for its message.
    """
    # split_tokens falls back to whitespace splitting on an unbalanced
    # quote rather than giving up. Abstaining there would hand back an
    # evasion — the very thing that helper exists to prevent — and this
    # validator blocks, so under-tokenizing is the dangerous direction.
    tokens = split_tokens(command=segment)
    if not tokens:
        return "", []

    verb = PurePosixPath(tokens[0]).name
    if verb not in _WRITERS:
        return "", []

    operands: list[str] = []
    targets: list[str] = []
    # A shared iterator consumes a flag's value at the point of match, so
    # no "skip the next one" flag outlives the branch that set it — with
    # booleans the ORDER of the checks below is load-bearing.
    remaining = iter(tokens[1:])
    for token in remaining:
        if token in _DEST_FLAGS:
            targets.append(next(remaining, ""))
            continue
        if token in _VALUE_FLAGS:
            next(remaining, None)
            continue
        flag, _, inline_value = token.partition("=")
        if inline_value and flag in _DEST_FLAGS:
            targets.append(inline_value)
            continue
        if token.startswith("-") and token != "-":
            continue
        operands.append(token)

    # A target flag makes every operand a source, so it wins outright.
    if targets:
        return verb, targets
    if verb in _ALL_ARG_WRITERS:
        return verb, operands
    # cp/mv/install write the last operand; a lone operand is a source
    # with no destination, which writes nothing.
    return verb, operands[-1:] if len(operands) >= 2 else []


def _working_tree(*, cwd: str) -> PurePosixPath:
    """The checkout ``cwd`` sits in, or ``cwd`` itself if it is not in one.

    ``cwd`` is the caller's current directory, which is often but not
    always the checkout root. Walking up for the ``.git`` entry — a file
    in a worktree, a directory in a main checkout — finds the real root
    with a few ``exists()`` calls and no subprocess.
    """
    here = Path(cwd)
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return PurePosixPath(candidate)
    return PurePosixPath(cwd)


def _lands_in_working_tree(*, destination: str, cwd: str) -> bool:
    """True when ``destination`` resolves to a path inside the checkout.

    ``~`` and ``$VAR`` forms are treated as outside: they are absolute
    once expanded and the expansion is not this validator's job to
    guess. A relative path is resolved against ``cwd``, since that is
    where the command runs.
    """
    if destination.startswith(("~", "$")):
        return False

    root = PurePosixPath(posixpath.normpath(str(_working_tree(cwd=cwd))))
    if destination.startswith("/"):
        candidate = destination
    else:
        candidate = posixpath.join(cwd, destination)
    # normpath is pure string manipulation — no stat, no symlink follow —
    # so it collapses ".." without the filesystem access that
    # Path.resolve() would add to a per-Bash-call check.
    resolved = PurePosixPath(posixpath.normpath(candidate))

    return resolved != root and resolved.is_relative_to(root)


def _message(*, verb: str, destination: str) -> str:
    return (
        f"⛔  `{verb}` into the working tree blocked — it writes "
        f"`{destination}` without reaching the Edit|Write hook.\n\n"
        "Use `Read` on the source, then `Write` the destination.\n\n"
        "Why: a shell copy skips validate-edit-write.py, leaves file-state "
        "tracking with no baseline for a later Edit, and — the reason this "
        "rule exists — places content the agent never read. Copying is not "
        "reading, so a `cp` cannot discover that what it moved is wrong "
        "(GH-1245).\n\n"
        "Writing OUTSIDE the working tree is unaffected — a /tmp staging "
        "copy or a move between scratch paths is still allowed."
    )


@dataclass
class WriteDestinationValidator(ValidatorBase):
    name: ClassVar[str] = "write-destination"
    rule_id: ClassVar[str] = "DX017"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        if not inp.cwd:
            return False
        return any(verb in inp.command for verb in _WRITERS)

    def validate(self, inp: HookInput) -> HookResult | None:
        for segment in _segments(inp.command):
            verb, destinations = _destinations(segment=segment)
            for destination in destinations:
                if _lands_in_working_tree(destination=destination, cwd=inp.cwd):
                    return HookResult(
                        message=_message(verb=verb, destination=destination),
                        rule_id=self.rule_id,
                    )
        return None
