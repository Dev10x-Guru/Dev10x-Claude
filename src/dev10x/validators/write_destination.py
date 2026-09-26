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
the working tree* AND names a text/source file extension is denied. A
``/tmp`` → ``/tmp`` copy, a staging move under a scratch root, or any
write outside the checkout is left alone — those are legitimate shell
work and blocking them would be friction with no safety payoff. A
binary destination (``.pdf``, ``.png``, ``.zip``, ...) is also left
alone regardless of location (GH-1455): the rule's remedy is
``Read`` then ``Write``, and ``Write`` cannot produce binary content,
so blocking a binary leaves the caller with no compliant path at
all — a same-tree rename of an invoice PDF had nowhere to go. The
blocked-extension set is a closed allowlist of formats normally
authored in a session (``_DEFAULT_BLOCKED_EXTENSIONS``) rather than
sniffing file bytes: a destination may not exist yet, and a byte sniff
costs a ``stat``/read on every Bash call this validator's fast path
lets through. The set is overridable via ``DEV10X_DX017_*`` env vars
(see below).

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

import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import split_tokens, substitution_bodies
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

#: Text/source extensions this validator guards (GH-1455). Everything NOT
#: on this list — every binary format (PDF, image, archive, font, office
#: doc, ...) — passes through untouched, because the rule's own remedy
#: ("Read then Write") cannot apply to a format Write cannot produce.
#: Overridable per session via the env vars below; leading dot optional,
#: matching is case-insensitive.
_DEFAULT_BLOCKED_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".svelte",
        ".vue",
        ".astro",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".less",
        ".json",
        ".jsonc",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".env",
        ".conf",
        ".md",
        ".mdx",
        ".rst",
        ".txt",
        ".csv",
        ".tsv",
        ".xml",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".bat",
        ".dockerfile",
        ".tf",
        ".hcl",
        ".graphql",
        ".proto",
        ".plantuml",
        ".puml",
        ".dsl",
        ".lock",
        ".svg",
    }
)

#: Extensionless filenames that are still text — matched case-insensitively
#: against the destination's basename.
_BLOCKED_EXTENSIONLESS_NAMES = frozenset(
    {"dockerfile", "makefile", "license", "readme", ".gitignore", ".editorconfig"}
)

#: `BLOCKED` REPLACES the default set; `EXTRA` then adds to whatever is in
#: effect; `ALLOW` then removes from that — a one-off exemption without
#: restating the whole list (GH-1455 addendum). Read once per hook
#: invocation, same as the hook's other env-driven knobs.
_ENV_BLOCKED = "DEV10X_DX017_BLOCKED_EXTENSIONS"
_ENV_EXTRA = "DEV10X_DX017_EXTRA_EXTENSIONS"
_ENV_ALLOW = "DEV10X_DX017_ALLOW_EXTENSIONS"


def _normalize_ext(raw: str) -> str:
    ext = raw.strip().lower()
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


def _parse_ext_list(*, value: str) -> frozenset[str]:
    return frozenset(
        normalized for item in value.split(",") if (normalized := _normalize_ext(item))
    )


def _effective_blocked_extensions() -> frozenset[str]:
    blocked = _DEFAULT_BLOCKED_EXTENSIONS
    replacement = os.environ.get(_ENV_BLOCKED, "")
    if replacement.strip():
        blocked = _parse_ext_list(value=replacement)
    extra = os.environ.get(_ENV_EXTRA, "")
    if extra.strip():
        blocked = blocked | _parse_ext_list(value=extra)
    allow = os.environ.get(_ENV_ALLOW, "")
    if allow.strip():
        blocked = blocked - _parse_ext_list(value=allow)
    return blocked


def _is_blocked_destination_type(*, destination: str) -> bool:
    """Whether ``destination`` names a format DX017 still guards (GH-1455).

    A binary format can never round-trip through ``Read`` → ``Write``, so
    blocking it would leave the caller with no compliant path — this is
    the check that lets a same-tree PDF rename through while still
    denying a same-tree copy of a source file.
    """
    name = PurePosixPath(destination).name
    if name.lower() in _BLOCKED_EXTENSIONLESS_NAMES:
        return True
    suffix = PurePosixPath(name).suffix.lower()
    if not suffix:
        return False
    return suffix in _effective_blocked_extensions()

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
        # cp/mv/install with -t/--target-directory write each source's
        # BASENAME under the target directory (`-t DEST a.py b.json`
        # writes DEST/a.py and DEST/b.json) — so the real destination's
        # extension comes from the source, not from the (typically
        # extensionless) directory named in `targets`. Resolving it here
        # is what lets GH-1455's extension check see the right file
        # instead of always seeing a bare directory.
        if verb in _LAST_ARG_WRITERS and operands:
            return verb, [
                posixpath.join(target, PurePosixPath(operand).name)
                for target in targets
                for operand in operands
            ]
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
        "copy or a move between scratch paths is still allowed. A binary "
        "destination (PDF, image, archive, ...) is unaffected too — "
        "Write cannot produce it, so this rule does not guard it."
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
                if not _lands_in_working_tree(destination=destination, cwd=inp.cwd):
                    continue
                if not _is_blocked_destination_type(destination=destination):
                    continue
                return HookResult(
                    message=_message(verb=verb, destination=destination),
                    rule_id=self.rule_id,
                )
        return None
