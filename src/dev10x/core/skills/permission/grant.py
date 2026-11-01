"""Triage a prompted command, then pre-approve it everywhere (GH-1676).

A supervisor who approves a useful command by hand meets the same
prompt again in the next worktree, the next project, and the next
background subagent. Granting a rule used to mean editing one settings
file by hand, so the fix never travelled.

Granting is also often the wrong fix. The friction fix order is
*source > normalize > grant*: a command the command-skill map routes to a
skill or MCP tool should use that route; a command whose shape no allow
rule can match (chaining, ``${...}``, escaped quotes) should be rewritten;
a read outside the working directories needs ``additionalDirectories`` or
a ``Read()`` rule, not a Bash rule; and a sensitive target must keep its
prompt (DX014). :func:`triage` decides which of those applies before
:func:`grant_everywhere` writes anything, and the writer refuses every
verdict but :attr:`Verdict.GRANT`.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from dev10x.core import validators as _validators
from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.bash_tokens import (
    ANY_CASE_ENV_VAR_RE,
    split_tokens,
    strip_quoted_spans,
)
from dev10x.domain.common.mcp_tool_name import McpToolName
from dev10x.domain.common.result import Result, err, ok
from dev10x.domain.rules.validation_rule import Compensation, MatchingRule
from dev10x.domain.sensitivity import SensitivityClassifier, name_is_sensitive, operand_tokens
from dev10x.skills.permission.backup import backed_up_write
from dev10x.skills.permission.catalog_write import partition_writable
from dev10x.skills.permission.exec_capable import exec_flag, is_interpreter
from dev10x.skills.permission.generalize import generalize_rule_shape

SKILL_MAP_PATH = Path(_validators.__file__).parent / "command-skill-map.yaml"

# How many subcommand words a tool's rule keeps. `gh pr view` needs two
# to stay read-only; `git status` needs one; `rg` needs none. A listed
# tool whose subcommand cannot be read (`git -C x status`) derives no
# rule at all: falling back to the bare executable would grant the
# whole tool, `git push --force` included.
_SUBCOMMAND_DEPTH: dict[str, int] = {
    "aws": 2,
    "cargo": 1,
    "dev10x": 2,
    "docker": 1,
    "gcloud": 2,
    "gh": 2,
    "git": 1,
    "kubectl": 1,
    "npm": 1,
    "pnpm": 1,
    "systemctl": 1,
    "uv": 1,
    "yarn": 1,
}
_SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9-]*$")

# Executables whose allow rule is an arbitrary-code, privilege, egress or
# destruction primitive. `Bash(bash:*)` lets `bash -c "rm -rf /"` past a
# `Bash(rm -rf:*)` deny, because a deny matches only its literal prefix.
_UNGRANTABLE_EXECUTABLES = frozenset(
    {
        "awk",
        "bash",
        "builtin",
        "bun",
        "chmod",
        "chown",
        "chrt",
        "command",
        "curl",
        "dash",
        "dd",
        "deno",
        "doas",
        "env",
        "eval",
        "exec",
        "find",
        "fish",
        "ionice",
        "nc",
        "ncat",
        "nice",
        "node",
        "nohup",
        "npx",
        "perl",
        "php",
        "pkexec",
        "python",
        "python3",
        "rm",
        "ruby",
        "scp",
        "sed",
        "sh",
        "source",
        "ssh",
        "stdbuf",
        "su",
        "sudo",
        "taskset",
        "time",
        "timeout",
        "uvx",
        "watch",
        "wget",
        "xargs",
        "zsh",
    }
)
_UNGRANTABLE_PREFIXES = frozenset(
    {
        ("docker", "exec"),
        ("docker", "run"),
        ("gh", "api"),
        ("git", "push"),
        ("kubectl", "apply"),
        ("kubectl", "delete"),
        ("kubectl", "exec"),
        ("npm", "exec"),
        ("pnpm", "dlx"),
        ("pnpm", "exec"),
        ("uv", "run"),
        ("yarn", "dlx"),
    }
)
# GH-1687: a denylist misses every interpreter nobody thought to list
# (`deno`, `lua`, `watch`), so a whole-executable grant is refused unless
# the tool is known safe at that depth. Seeded from the bare rules the
# catalogs already ship, minus their interpreters, wrappers and egress
# tools. `make` stays: it runs the repo's own recipes, which the agent can
# already edit. A sensitive operand is still refused separately (DX014).
_BARE_GRANTABLE_EXECUTABLES = frozenset(
    {
        "actionlint",
        "basename",
        "cat",
        "column",
        "comm",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "egrep",
        "fgrep",
        "file",
        "gitlint",
        "grep",
        "head",
        "jq",
        "ls",
        "make",
        "nl",
        "printf",
        "pup",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "shellcheck",
        "sort",
        "stat",
        "tail",
        "tomlq",
        "tr",
        "tree",
        "uniq",
        "wc",
        "which",
        "xq",
        "yamllint",
        "yq",
    }
)
_VETTED_EXECUTABLES = (
    _BARE_GRANTABLE_EXECUTABLES | _UNGRANTABLE_EXECUTABLES | frozenset(_SUBCOMMAND_DEPTH)
)
_RULE_WILDCARD_SUFFIX_RE = re.compile(r"(?::\*| \*)$")
_PATH_ROOT_RE = re.compile(r"^(?://|/|~/|\./)?")

# Verbs whose path operands the harness checks against the working
# directories. A Bash allow rule never lifts that check, so a read
# outside them keeps prompting however the rule is spelled.
_READ_VERBS = frozenset(
    {
        "awk",
        "cat",
        "diff",
        "du",
        "file",
        "find",
        "grep",
        "head",
        "jq",
        "less",
        "ls",
        "rg",
        "sed",
        "stat",
        "tail",
        "tree",
        "wc",
        "yq",
    }
)

_CHAINING_RE = re.compile(r"&&|\|\||;|\||\n")
_EXPANSION_RE = re.compile(r"\$\{|\$\(|\$[A-Za-z_]|`")
# Credential and secret stores named by their directory or file, with or
# without a trailing slash or glob. The DX014 operand patterns need an
# exact filename, so `rg x ~/.ssh` and `Read(~/.aws/**)` slipped past them.
# Kept local on purpose: widening DX014 itself would prompt on a plain
# `ls ~/.ssh`, which hook-patterns.md requires to stay silent. Granting a
# rule is the stricter question, so it gets the stricter list.
_SENSITIVE_ROOT_RE = re.compile(
    r"(?:(?:^|/|~)\.(?:ssh|aws|gnupg|kube|docker|netrc|pgpass|git-credentials|env)"
    r"|\.config/gh)(?![\w-])"
)
_OBFUSCATION_RE = re.compile(r"\\[\"']|\"\"|''")
_REDIRECT_RE = re.compile(r"<<|>")
_STRUCTURED_RULE_RE = re.compile(r"^[A-Za-z]+\(.*\)$", re.DOTALL)


class Verdict(StrEnum):
    """The one fix :func:`triage` recommends, in friction-fix order."""

    REFUSE_SENSITIVE = "refuse-sensitive"
    TOO_BROAD = "too-broad"
    DENIED = "denied"
    USE_ALTERNATIVE = "use-alternative"
    NORMALIZE = "normalize"
    OUTSIDE_WORKDIR = "outside-workdir"
    ALREADY_ALLOWED = "already-allowed"
    GRANT = "grant"


@dataclass(frozen=True)
class Triage:
    """What to do about one prompted command, and why."""

    target: str
    verdict: Verdict
    rule: str
    reason: str
    advice: list[str] = field(default_factory=list)
    files_missing: list[Path] = field(default_factory=list)
    files_unreadable: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "verdict": str(self.verdict),
            "rule": self.rule,
            "reason": self.reason,
            "advice": list(self.advice),
            "files_missing": [str(path) for path in self.files_missing],
            "files_unreadable": [str(path) for path in self.files_unreadable],
        }


def is_rule(target: str) -> bool:
    """True when ``target`` is already a permission rule, not a command."""
    return McpToolName.is_mcp(target) or bool(_STRUCTURED_RULE_RE.match(target.strip()))


def derive_rule(*, command: str) -> str:
    """Turn a concrete command into the reusable rule that would cover it.

    Keeps the executable plus the subcommand words its tool needs to stay
    meaningful, then hands the result to ``generalize_rule_shape`` so a
    verb-blind prefix is narrowed rather than granted. Returns ``""`` when
    no safe rule exists, which :func:`triage` reports as too broad.
    """
    tokens = split_tokens(command=command.strip())
    if not tokens:
        return ""
    head = tokens[0]
    depth = _SUBCOMMAND_DEPTH.get(head, 0)
    words = [head, *tokens[1 : 1 + depth]]
    if len(words) != depth + 1 or not all(_SUBCOMMAND_RE.match(w) for w in words[1:]):
        return ""
    return generalize_rule_shape(f"Bash({' '.join(words)}:*)")


def bash_prefix(*, rule: str) -> str | None:
    """The literal command prefix a ``Bash(...)`` rule allows, or None."""
    parsed = AllowRule.parse(rule)
    if parsed.tool != "Bash":
        return None
    return _RULE_WILDCARD_SUFFIX_RE.sub("", parsed.inner).strip()


def breadth_problem(*, rule: str) -> str | None:
    """Why ``rule`` would grant far more than one approved command, or None."""
    if not rule:
        return "No reusable rule can be derived without granting the whole tool."
    if McpToolName.is_mcp(rule):
        return "An MCP wildcard grants every tool on the server." if "*" in rule else None
    prefix = bash_prefix(rule=rule)
    if prefix is None:
        pattern = _PATH_ROOT_RE.sub("", AllowRule.parse(rule).inner, count=1)
        return "The pattern starts with a wildcard." if pattern.startswith("*") else None
    words = prefix.split()
    if not words or "*" in prefix:
        return "The command prefix is a wildcard."
    if Path(words[0]).name in _UNGRANTABLE_EXECUTABLES:
        return f"`{words[0]}` runs arbitrary code, escalates or deletes; approve each use."
    exec_problem = _exec_problem(words=words)
    if exec_problem:
        return exec_problem
    if tuple(words[:2]) in _UNGRANTABLE_PREFIXES:
        return f"`{' '.join(words[:2])}` can write or run anything; approve each use."
    if len(words) <= _SUBCOMMAND_DEPTH.get(words[0], 0):
        return f"`{prefix}` grants every `{words[0]}` subcommand, destructive ones included."
    unknown = _unknown_bare_executable(rule=rule)
    if unknown:
        return (
            f"`{unknown}` is not known safe to grant whole; it may run code or write. "
            f"Grant {_narrower_example(rule=rule)} instead."
        )
    return None


def _exec_problem(*, words: list[str]) -> str | None:
    """Why ``words`` would let a granted rule run another program (GH-1723)."""
    if is_interpreter(executable=words[0]):
        return (
            f"`{words[0]}` is an interpreter; a rule for it runs any script it is handed. "
            "Approve each use, or wrap the script and grant the wrapper."
        )
    flag = exec_flag(words=words)
    if flag:
        return f"`{words[0]} {flag}` executes another program; approve each use."
    return None


def _unknown_bare_executable(*, rule: str) -> str | None:
    """The executable a wildcard rule grants whole without being vetted."""
    if not rule or McpToolName.is_mcp(rule):
        return None
    parsed = AllowRule.parse(rule)
    prefix = bash_prefix(rule=rule)
    if not prefix or not _RULE_WILDCARD_SUFFIX_RE.search(parsed.inner):
        return None
    words = prefix.split()
    if len(words) != 1 or "*" in prefix or words[0] in _VETTED_EXECUTABLES:
        return None
    # A `FOO=1` head is not an executable; triage's normalize advice fixes it.
    if ANY_CASE_ENV_VAR_RE.match(words[0]):
        return None
    return words[0]


def _narrower_example(*, rule: str) -> str:
    unknown = _unknown_bare_executable(rule=rule)
    return f"Bash({unknown} <subcommand>:*)" if unknown else "Bash(git status:*)"


def load_skill_map_rules(*, yaml_path: Path = SKILL_MAP_PATH) -> list[MatchingRule]:
    """Every Bash rule in the command-skill map, advisory ones included.

    The hook only loads ``hook_block`` rules, but an advisory route is
    still an alternative worth taking before granting a raw command.
    """
    from dev10x.config.loader import load_config

    return [rule for rule in load_config(yaml_path=yaml_path).rules if rule.matcher == "Bash"]


def _describe(*, compensation: Compensation) -> str:
    if compensation.skill:
        return f"Skill({compensation.skill})"
    if compensation.tool:
        return compensation.tool
    return compensation.alias or compensation.description or compensation.type


def _permissions(*, path: Path) -> dict[str, Any] | None:
    """The file's ``permissions`` block, or None when the file is unusable.

    Claude Code cannot load an unparseable or wrongly-shaped settings file
    either, so its rules are not live: it is reported rather than written.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    permissions = data.get("permissions", {})
    return permissions if isinstance(permissions, dict) else None


def _rules(*, permissions: dict[str, Any], key: str) -> list[str]:
    values = permissions.get(key, [])
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _signature(*, target: str) -> str:
    return target if is_rule(target) else f"Bash({target})"


def _covers(*, rules: Iterable[str], signature: str, rule: str) -> bool:
    return any(
        existing == rule or AllowRule.parse(existing).matches(signature) for existing in rules
    )


def _overlapped_deny(*, rule: str, denies: Iterable[str]) -> str | None:
    """A narrower deny the Bash ``rule`` would also allow, if any.

    The deny still wins at evaluation time, but granting `Bash(git push:*)`
    beside a deny of `Bash(git push --force:*)` widens the allow up to the
    rail the supervisor drew on purpose.
    """
    granted = bash_prefix(rule=rule)
    if not granted:
        return None
    for deny in denies:
        denied = bash_prefix(rule=deny)
        if denied and denied != granted and f"{denied} ".startswith(f"{granted} "):
            return deny
    return None


def _read_rule(*, path: Path) -> str:
    home = Path.home()
    if path.is_relative_to(home):
        return f"Read(~/{path.relative_to(home)})"
    return f"Read(/{path})"


def _normalized(*, path: Path) -> Path:
    return Path(os.path.normpath(path.expanduser()))


def _normalize_reasons(*, command: str) -> list[str]:
    unquoted = strip_quoted_spans(command=command)
    tokens = split_tokens(command=command)
    reasons: list[str] = []
    if tokens and ANY_CASE_ENV_VAR_RE.match(tokens[0]):
        reasons.append("Drop the leading env-var assignment; it shifts the rule prefix.")
    if _CHAINING_RE.search(unquoted.strip()):
        reasons.append("Split the chain into one Bash call per command.")
    if _EXPANSION_RE.search(command):
        reasons.append("Resolve the ${...}/$(...) expansion first; no allow rule matches one.")
    if _OBFUSCATION_RE.search(command):
        reasons.append("Avoid escaped or doubled quotes; they trip the harness obfuscation check.")
    if _REDIRECT_RE.search(unquoted):
        reasons.append("Use the Write tool instead of a heredoc or redirect.")
    return reasons


def _outside_paths(*, command: str, working_dirs: list[Path]) -> list[Path]:
    tokens = split_tokens(command=command)
    if not tokens or Path(tokens[0]).name not in _READ_VERBS:
        return []
    roots = [_normalized(path=directory) for directory in working_dirs]
    paths: list[Path] = []
    for token in operand_tokens(command=command)[1:]:
        anchored = token.startswith(("/", "~"))
        path = _normalized(path=Path(token) if anchored else roots[0] / token)
        if not any(path.is_relative_to(root) for root in roots):
            paths.append(path)
    return paths


def _sensitive(*, target: str) -> list[str]:
    if McpToolName.is_mcp(target):
        return [target] if name_is_sensitive(target) else []
    command = AllowRule.parse(target).inner if is_rule(target) else target
    matches = [match.matched_text for match in SensitivityClassifier().classify(command=command)]
    roots = [
        token for token in operand_tokens(command=command) if _SENSITIVE_ROOT_RE.search(token)
    ]
    return list(dict.fromkeys([*matches, *roots]))


def triage(
    *,
    target: str,
    settings_files: list[Path],
    working_dirs: list[Path],
    base_denies: Iterable[str] = (),
    skill_map_rules: list[MatchingRule] | None = None,
) -> Triage:
    """Decide the one fix for ``target`` — a command or a permission rule.

    Checks run in friction-fix order and the first hit wins: a sensitive
    target keeps its prompt, a deliberate deny stays a deny (GH-972),
    a routed command uses its route — even when its shape alone made the
    derived rule too broad, as a leading ``gog`` global flag does
    (GH-1667) — an unmatchable shape is rewritten, a
    read outside the working directories gets a directory or ``Read()``
    fix, and only then is a rule granted to the files that lack it.
    """
    target = target.strip()
    if is_rule(target):
        rule, command = target, bash_prefix(rule=target)
    else:
        rule, command = derive_rule(command=target), target
    signature = _signature(target=target)

    def verdict(*, kind: Verdict, reason: str, advice: list[str], **files: list[Path]) -> Triage:
        return Triage(
            target=target,
            verdict=kind,
            rule=rule,
            reason=reason,
            advice=advice,
            **files,
        )

    sensitive = _sensitive(target=target)
    if sensitive:
        return verdict(
            kind=Verdict.REFUSE_SENSITIVE,
            reason=f"Sensitive target ({', '.join(sensitive)}); DX014 keeps the prompt.",
            advice=[
                "Approve it case by case, or bless one exact probe in "
                "~/.config/Dev10x/sensitivity-exceptions.yaml."
            ],
        )

    def routed_verdict(*, routed: MatchingRule) -> Triage:
        return verdict(
            kind=Verdict.USE_ALTERNATIVE,
            reason=f"The command-skill map routes this command ({routed.name}).",
            advice=[_describe(compensation=c) for c in routed.compensations],
        )

    def route() -> MatchingRule | None:
        if not command:
            return None
        rules = load_skill_map_rules() if skill_map_rules is None else skill_map_rules
        return next(
            (r for r in rules if r.compensations and r.matches_command(command=command)),
            None,
        )

    command_words = split_tokens(command=command) if command else []
    # GH-1723: derive_rule drops the flags, so check the command itself.
    runs_programs = _exec_problem(words=command_words) if command_words else None
    too_broad = breadth_problem(rule=rule) or runs_programs
    if too_broad:
        # GH-1667
        rerouted = route()
        if rerouted is not None:
            return routed_verdict(routed=rerouted)
        narrower = (
            "Keep approving it per use, or put the command in a script or MCP tool and grant that."
            if runs_programs
            else "Keep approving it per use, or grant a narrower rule naming the exact "
            f"subcommand, e.g. {_narrower_example(rule=rule)}."
        )
        return verdict(kind=Verdict.TOO_BROAD, reason=too_broad, advice=[narrower])

    loaded = {path: _permissions(path=path) for path in settings_files}
    readable = {path: block for path, block in loaded.items() if block is not None}
    unreadable = [path for path, block in loaded.items() if block is None]

    denies = set(base_denies)
    for block in readable.values():
        denies.update(_rules(permissions=block, key="deny"))
    overlapped = _overlapped_deny(rule=rule, denies=denies)
    if overlapped or _covers(rules=denies, signature=signature, rule=rule):
        return verdict(
            kind=Verdict.DENIED,
            reason=(
                f"The rule would also cover the deliberate deny {overlapped}."
                if overlapped
                else "A deny rule names this shape on purpose; a grant would fight it."
            ),
            advice=["Run the exact command yourself with the `!` prefix if it is needed."],
        )

    routed = route()
    if routed is not None:
        return routed_verdict(routed=routed)

    if command:
        reasons = _normalize_reasons(command=command)
        if reasons:
            return verdict(
                kind=Verdict.NORMALIZE,
                reason="No allow rule can match this command shape.",
                advice=reasons,
            )

        outside = _outside_paths(command=command, working_dirs=working_dirs)
        if outside:
            return verdict(
                kind=Verdict.OUTSIDE_WORKDIR,
                reason="It reads outside the working directories; a Bash rule cannot lift that.",
                advice=[
                    *(
                        f"Add {path.parent} to permissions.additionalDirectories"
                        for path in outside
                    ),
                    *(f"Or use the Read tool with {_read_rule(path=path)}" for path in outside),
                ],
            )

    missing = [
        path
        for path, block in readable.items()
        if not _covers(
            rules=_rules(permissions=block, key="allow"), signature=signature, rule=rule
        )
    ]
    repair = [f"Repair or remove unreadable settings file {path}" for path in unreadable]
    if not missing:
        return verdict(
            kind=Verdict.ALREADY_ALLOWED,
            reason="Every readable settings file already allows it.",
            advice=["Run dev10x:diag-friction on the exact command that prompted.", *repair],
            files_unreadable=unreadable,
        )
    return verdict(
        kind=Verdict.GRANT,
        reason=f"No better fix applies; {len(missing)} settings file(s) lack the rule.",
        advice=repair,
        files_missing=missing,
        files_unreadable=unreadable,
    )


def _append_allow(*, path: Path, rule: str) -> None:
    with backed_up_write(path=path) as data:
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        if rule not in allow:
            allow.append(rule)


_ALREADY_COVERED = "already covered"


def _grant_one(*, path: Path, rule: str, signature: str, dry_run: bool) -> str | None:
    """Write ``rule`` into one file; return why it was not written, or None."""
    block = _permissions(path=path)
    if block is None:
        return "unreadable settings"
    if _covers(rules=_rules(permissions=block, key="allow"), signature=signature, rule=rule):
        return _ALREADY_COVERED
    if dry_run:
        return None
    try:
        _append_allow(path=path, rule=rule)
    except (OSError, ValueError) as exc:
        return str(exc)
    return None


def grant_everywhere(
    *,
    target: str,
    settings_files: list[Path],
    working_dirs: list[Path],
    base_denies: Iterable[str] = (),
    dry_run: bool = False,
    confirmed_rule: str | None = None,
    skill_map_rules: list[MatchingRule] | None = None,
) -> Result[dict[str, Any]]:
    """Grant ``target``'s rule to every settings file that lacks it.

    ``confirmed_rule``, when given, must equal the rule triage derives.
    The approval prompt on a tool call shows its arguments, not the rule
    it will write, so a caller echoing the rule is what lets the person
    approving see that `bash -c ls` would have become `Bash(bash:*)`.

    Re-runs :func:`triage` so the writer cannot be reached past a better
    fix, and refuses any verdict but GRANT. A git-tracked
    ``settings.json`` is redirected to its ``settings.local.json``
    sibling (GH-1136). A deny in any readable settings file or in the
    catalog refuses the grant for every file, since a narrower deny the
    rule overlaps is a decision the grant must not route around (GH-972).
    One file failing to write does not stop the others; the call then
    returns an error naming each failure so the partial grant is visible.
    """
    result = triage(
        target=target,
        settings_files=settings_files,
        working_dirs=working_dirs,
        base_denies=base_denies,
        skill_map_rules=skill_map_rules,
    )
    if result.verdict is not Verdict.GRANT:
        return err(
            f"Not granted ({result.verdict}): {result.reason}",
            triage=result.to_dict(),
        )
    if confirmed_rule is not None and confirmed_rule != result.rule:
        return err(
            f"Not granted: triage derived {result.rule}, but {confirmed_rule} was confirmed.",
            triage=result.to_dict(),
        )

    writable, messages = partition_writable(
        settings_files=result.files_missing,
        redirect_tracked=True,
    )
    signature = _signature(target=result.target)
    granted: list[str] = []
    failed: list[str] = []
    for path in writable:
        problem = _grant_one(path=path, rule=result.rule, signature=signature, dry_run=dry_run)
        if problem == _ALREADY_COVERED:
            continue
        if problem:
            failed.append(str(path))
            messages.append(f"  FAILED {path}: {problem}")
            continue
        granted.append(str(path))
        messages.append(f"  + {result.rule}  {path}")
    payload = {
        "rule": result.rule,
        "granted": granted,
        "failed": failed,
        "dry_run": dry_run,
        "messages": messages,
        "triage": result.to_dict(),
    }
    if failed:
        return err(
            f"Granted {result.rule} in {len(granted)} file(s); {len(failed)} failed.",
            **payload,
        )
    return ok(payload)


__all__ = [
    "SKILL_MAP_PATH",
    "Triage",
    "Verdict",
    "bash_prefix",
    "breadth_problem",
    "derive_rule",
    "grant_everywhere",
    "is_rule",
    "load_skill_map_rules",
    "triage",
]
