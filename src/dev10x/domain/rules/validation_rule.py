from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property, lru_cache
from typing import Any

from dev10x.domain.common.bash_tokens import ANY_CASE_ENV_VAR_RE, split_tokens

_SUBCOMMAND_BOUNDARY = r"(?![-\w])"

_SEARCH_TOOLS = frozenset({"find", "grep", "fgrep", "egrep", "rg", "ag", "ack", "xargs"})


class MatchPosition(StrEnum):
    """Which parts of a command a rule's patterns are searched against (GH-1084).

    Members preserve their lowercase string value so the YAML
    ``match_position:`` key round-trips unchanged, matching the
    ``FrictionLevel`` convention.
    """

    # The whole command string — the historical behaviour, and right for a
    # rule about a token's mere presence (a rotting version-pinned path is
    # a defect as a `cat` argument too).
    ANYWHERE = "anywhere"

    # Only the tokens naming a program being RUN. This is what a rule
    # guarding a script path actually means: `git-push-safe.sh` as a
    # pattern was blocking `pre-commit run --files <path>/git-push-safe.sh`
    # and `mv <path>/git-push-safe.sh <path>/oldguard.sh`, neither of which
    # executes anything.
    INVOCATION = "invocation"


# Operators that end one command and begin another, so each side carries
# its own invocation position. `echo hi && <path>/git-push-safe.sh` runs
# the script even though it is not the first token of the string.
_SEGMENT_SEPARATOR_RE = re.compile(r"\|\||&&|[;|&\n]")

# `find … -exec <cmd> …` runs `<cmd>`, so the token after the flag is an
# invocation position even though it is not the segment's executable.
_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})

# Wrappers that pass execution through to a following program.
_SHELL_WRAPPERS = frozenset({"bash", "sh"})


def _executable_token(*, tokens: list[str]) -> str:
    """The token naming the program a command segment runs, or ``""``.

    Strips shell wrappers (``bash``, ``sh``) and environment prefixes in
    both spellings — ``env VAR=x cmd`` and the bare ``VAR=x cmd`` — so a
    guarded script cannot be reached by prefixing an assignment.

    A wrapper's inline payload (``sh -c '<script> …'``) resolves to the
    ``-c`` flag rather than to the script, so this never looks inside it.
    That is deliberate and matches GH-210, which wants
    ``bash -c 'find … -name <script>'`` allowed; inline shell execution
    is the execution-safety validator's charge (DX003 runs earlier in
    the chain and denies ``-c`` outright), not this rule's.
    """
    idx = 0
    while idx < len(tokens):
        head = tokens[idx]
        if head in _SHELL_WRAPPERS or ANY_CASE_ENV_VAR_RE.match(head):
            idx += 1
            continue
        if head == "env":
            idx += 1
            while idx < len(tokens) and "=" in tokens[idx]:
                idx += 1
            continue
        return head
    return ""


def _invocation_tokens(*, command: str) -> list[str]:
    """Every token in ``command`` that names a program being executed.

    One per shell segment, plus the argument of any ``find -exec``-style
    flag — the shape that keeps ``find . -name '*.sh' -exec
    <script> {} ;`` blocked (GH-210) even though ``find`` is the
    segment's own executable.

    Segments are split on raw operator characters, before tokenizing, so
    a separator inside a quoted string splits too. That errs toward
    reporting an extra invocation token rather than missing one, which is
    the safe direction for a guard (GH-1049 gap 6).
    """
    invoked: list[str] = []
    for segment in _SEGMENT_SEPARATOR_RE.split(command):
        tokens = split_tokens(command=segment)
        executable = _executable_token(tokens=tokens)
        if executable:
            invoked.append(executable)
        invoked.extend(
            tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token in _EXEC_FLAGS
        )
    return invoked


# Executables that accept *global* options before their subcommand, so the
# subcommand is not necessarily the second token (GH-931 finding 3).
_SUBCOMMAND_EXECUTABLES = frozenset({"git", "gh"})

# Global options consuming a following value (`git -C /path push`) — either as
# a separate token or in `--opt=value` form.
_GLOBAL_VALUE_OPTIONS = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
        "--config-env",
        "--repo",
        "-R",
    }
)

# Global options taking no value (`git --no-pager push`).
_GLOBAL_FLAG_OPTIONS = frozenset(
    {
        "-p",
        "-P",
        "--paginate",
        "--no-pager",
        "--bare",
        "--literal-pathspecs",
        "--no-replace-objects",
        "--no-optional-locks",
    }
)


def _resolved_executable(command: str) -> str:
    """Return the resolved executable basename for a shell command.

    Strips shell wrappers (``bash``, ``sh``, ``env VAR=x``) so a search
    tool invoked via ``bash`` is still recognized. Returns an empty
    string when the command is malformed.
    """
    return _executable_token(tokens=split_tokens(command=command)).split("/")[-1]


def _unquoted(command: str) -> str:
    """Return ``command`` with the contents of quoted spans removed.

    Shell metacharacters are only metacharacters outside quotes. Callers
    that scan for a pipeline, a redirect, or a chain need to look at the
    shell's view of the string, not at regex syntax a user typed inside
    an argument.
    """
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in command:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            continue
        out.append(ch)
    return "".join(out)


def is_search_command(*, command: str) -> bool:
    """Return True when the resolved executable is a filesystem search tool.

    Used by :meth:`MatchingRule.matches_command` to suppress false positives where
    a rule pattern matches a filename appearing as a *search argument*
    (e.g. ``find -name 'git-push-safe.sh'``) rather than a command being
    executed (GH-210). Commands containing ``-exec`` or shell pipelines
    keep their normal evaluation because they can run the searched-for
    binary.

    The pipeline test reads the **unquoted** command (GH-1214 finding 6).
    A `|` inside a quoted argument is regex alternation, not a pipe, so
    `grep -E 'manage\\.py|gh pr edit|update_pr' brief.md` was read as a
    pipeline, lost this exemption, and was denied as a `gh pr edit` call —
    a supervisor auditing a brief for banned shapes cannot grep for the
    shapes by name. Searching for the literal text of a hook-blocked
    command is exactly what a search tool is for.

    Public because the exemption belongs to any validator that matches a
    command name against a raw string, not only to rule evaluation:
    DX005 (pr-base) denied ``rg -n 'gh pr create --body-file' skills/``
    for lacking a ``--base`` flag, the same defect in a validator that
    never reaches :meth:`MatchingRule.matches_command`.
    """
    bare = _unquoted(command)
    if "|" in bare or "-exec" in bare:
        return False
    return _resolved_executable(command=command) in _SEARCH_TOOLS


@lru_cache(maxsize=256)
def _strip_global_options(*, command: str) -> str:
    """Return ``command`` with git/gh global options removed.

    Rule patterns are command-name prefixes (``git push``, ``gh pr create``)
    matched with :meth:`re.Pattern.search`. A global option between the
    executable and the subcommand breaks that adjacency, so ``git -C /path
    push`` matched no ``git push`` rule and the guard was evadable by a
    trivial reformulation (GH-931 finding 3). Normalizing here fixes every
    ``git <verb>`` / ``gh <verb>`` rule at once instead of hardening 42 YAML
    patterns individually.

    Generalizes the ``-C``-only rewriting that
    :data:`~dev10x.domain.common.bash_tokens.GIT_C_DIR_RE` supports for
    DX007's advisory no-op check — that regex covers one option and only
    fires when the path equals the CWD, so it cannot close this hole. Extend
    the option sets above rather than adding a second normalizer (GH-583 N24
    is the cautionary tale for duplicating git-token knowledge).

    Cached because the result depends only on the command string while
    :meth:`MatchingRule.matches_command` is called once per rule — ~42 times
    per Bash call against the shipped catalog. Re-tokenizing per rule would
    put avoidable work on the PreToolUse hook path, which has a documented
    latency budget and a CI regression gate.

    Commands whose executable takes no global options are returned unchanged,
    so a pattern appearing as an *argument* (``mktmp.sh git commit-msg``)
    keeps its existing non-match behavior.
    """
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return command
    if parts[0].split("/")[-1] not in _SUBCOMMAND_EXECUTABLES:
        return command

    idx = 1
    while idx < len(parts):
        token = parts[idx]
        if token in _GLOBAL_VALUE_OPTIONS:
            idx += 2
            continue
        if token in _GLOBAL_FLAG_OPTIONS:
            idx += 1
            continue
        if "=" in token and token.split("=", 1)[0] in _GLOBAL_VALUE_OPTIONS:
            idx += 1
            continue
        break
    return " ".join([parts[0], *parts[idx:]])


def _anchor_subcommand(*, pattern: str) -> str:
    """Anchor a CLI subcommand pattern at the right edge.

    YAML patterns like ``git commit`` or ``gh pr create`` are
    command-name prefixes; without a right-edge boundary, ``git commit``
    matches inside ``git commit-msg`` (an argument value), producing
    false positives (GH-84). Append a negative lookahead so the
    pattern's last token cannot be followed by another word or hyphen
    character.

    Patterns already ending in a regex anchor (``$``, ``\\b``) or an
    explicit lookaround are left untouched.
    """
    if pattern.endswith(("$", r"\b")) or pattern.endswith((")", "]")):
        return pattern
    return pattern + _SUBCOMMAND_BOUNDARY


@dataclass(frozen=True)
class Compensation:
    type: str
    skill: str = ""
    tool: str = ""
    alias: str = ""
    guardrails: str = ""
    fallback: str = ""
    description: str = ""

    @classmethod
    def from_yaml_entry(cls, entry: dict[str, Any]) -> Compensation:
        return cls(**{k: v for k, v in entry.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class MatchingRule:
    name: str
    patterns: list[str] = field(default_factory=list)
    matcher: str = "Bash"
    except_: list[str] = field(default_factory=list)
    compensations: list[Compensation] = field(default_factory=list)
    hook_block: bool = True
    reason: str = ""
    message: str = ""
    related: list[str] = field(default_factory=list)
    file_pattern: str = ""
    file_names: list[str] = field(default_factory=list)
    file_prefixes: list[str] = field(default_factory=list)
    file_substrings: list[str] = field(default_factory=list)
    content_pattern: str = ""
    match_position: str = MatchPosition.ANYWHERE

    def __post_init__(self) -> None:
        # Fail loud on a typo rather than silently degrading to ANYWHERE,
        # which would un-anchor the rule with no diagnostic.
        MatchPosition(self.match_position)

    @cached_property
    def compiled_patterns(self) -> list[re.Pattern[str]]:
        return [re.compile(_anchor_subcommand(pattern=p)) for p in self.patterns]

    @cached_property
    def compiled_file_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.file_pattern) if self.file_pattern else None

    @cached_property
    def compiled_content_pattern(self) -> re.Pattern[str] | None:
        return re.compile(self.content_pattern) if self.content_pattern else None

    def matches_file(self, *, file_path: str) -> bool:
        if self.compiled_file_pattern and self.compiled_file_pattern.search(file_path):
            return True
        name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        if name in self.file_names:
            return True
        if any(name.startswith(p) for p in self.file_prefixes):
            return True
        return any(s in file_path for s in self.file_substrings)

    def matches_content(self, *, content: str) -> bool:
        if self.compiled_content_pattern is None:
            return True
        return self.compiled_content_pattern.search(content) is not None

    def format_message(self, *, file_path: str) -> str:
        text = self.message or self.reason or "BLOCKED"
        msg = text.format(file_path=file_path)
        for comp in self.compensations:
            desc = comp.description
            if desc:
                msg += f"\n\n{desc.strip()}"
        return msg

    def match_candidates(self, *, command: str) -> list[str]:
        """The strings this rule's patterns are searched against.

        The single seam for "what may a pattern match" — extended once for
        global-option evasion (GH-931) and once for ``match_position``
        (GH-1084). A further position variant belongs here as another case,
        not as a second search loop bolted onto ``matches_command``.
        """
        if self.match_position == MatchPosition.INVOCATION:
            return _invocation_tokens(command=command)
        return [command, _strip_global_options(command=command)]

    def matches_command(self, *, command: str) -> bool:
        candidates = self.match_candidates(command=command)
        if not any(p.search(c) for p in self.compiled_patterns for c in candidates):
            return False
        if any(exc in command for exc in self.except_):
            return False
        if is_search_command(command=command):
            return False
        return True

    @classmethod
    def from_yaml_entry(cls, entry: dict[str, Any]) -> MatchingRule:
        compensations = [
            Compensation.from_yaml_entry(entry=c) for c in entry.get("compensations", [])
        ]
        return cls(
            name=entry.get("name", ""),
            patterns=entry.get("patterns", []),
            matcher=entry.get("matcher", "Bash"),
            except_=entry.get("except", []),
            compensations=compensations,
            hook_block=entry.get("hook_block", True),
            reason=entry.get("reason", ""),
            message=entry.get("message", ""),
            related=entry.get("related", []),
            file_pattern=entry.get("file_pattern", ""),
            file_names=entry.get("file_names", []),
            file_prefixes=entry.get("file_prefixes", []),
            file_substrings=entry.get("file_substrings", []),
            content_pattern=entry.get("content_pattern", ""),
            match_position=entry.get("match_position", MatchPosition.ANYWHERE),
        )


# Deprecated alias — the Matching Rule archetype's canonical name is
# ``MatchingRule`` (ADR-0007). ``Rule`` is retained for backward
# compatibility with existing imports and will be removed in a future
# release; prefer ``MatchingRule`` in new code.
Rule = MatchingRule
