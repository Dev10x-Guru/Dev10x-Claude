"""Validator: command prefix friction patterns.

Consolidates detect-and-chaining.py and block-alias-covered-commands.py.

Blocks patterns that shift the effective command prefix, breaking
allow-rule matching:
  1. && chaining with setup commands (mkdir, cd, export, etc.)
  2. ENV=value git ... prefix
  3. $(git merge-base ...) subshells
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

if TYPE_CHECKING:
    from dev10x.domain import HookRetry

SETUP_TOKENS = frozenset(
    ["mkdir", "cd", "export", "source", ".", "pushd", "popd", "touch", "unset"]
)

PATH_PREFIXES = (
    os.path.expanduser("~/.claude/skills/"),
    os.path.expanduser("~/.claude/tools/"),
    os.path.expanduser("~/.claude/hooks/"),
    "~/.claude/skills/",
    "~/.claude/tools/",
    "~/.claude/hooks/",
)

SETTINGS_FILES = [
    os.path.expanduser("~/.claude/settings.local.json"),
    os.path.expanduser("~/.claude/settings.json"),
]

GIT_C_RE = re.compile(r'\bgit\s+-C\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)')
ENV_PREFIX_GIT_RE = re.compile(r"^[A-Z_]+=\S*\s+git\b")
MERGE_BASE_RE = re.compile(r"\$\(git\s+merge-base\s+(\w+)\s+HEAD\)")
GIT_SUBCOMMAND_RE = re.compile(r"\bgit\s+(log|diff|rebase)\b")

CD_NOOP_RE = re.compile(r'^cd\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)\s*&&\s*(.*)')
CD_REVPARSE_RE = re.compile(r'^cd\s+"?\$\(git\s+rev-parse\s+--show-toplevel\)"?\s*&&\s*(.*)')
CD_GIT_CHAIN_RE = re.compile(r'^cd\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)\s*&&\s*git\b\s*(.*)')

CD_REVPARSE_MSG = (
    '\u26a0\ufe0f  `cd "$(git rev-parse --show-toplevel)"` is unnecessary.\n\n'
    "Git commands already operate from the repo root regardless of CWD.\n"
    "Drop the `cd ... &&` prefix and run the command directly:\n"
    "    {bare_command}\n\n"
    "If you need the repo root path, use:\n"
    "    git rev-parse --show-toplevel"
)

CD_NOOP_MSG = (
    "\u26a0\ufe0f  `cd {path}` is redundant — CWD is already `{cwd}`.\n\n"
    "Drop the `cd ... &&` prefix and run the command directly:\n"
    "    {bare_command}"
)

GIT_C_NOOP_MSG = (
    "\u26a0\ufe0f  `git -C {path}` is redundant — CWD is already `{cwd}`.\n\n"
    "Drop the `-C` flag and run the command directly:\n"
    "    {bare_command}"
)

CD_GIT_CHAIN_MSG = (
    "\u26a0\ufe0f  `cd {path} && git {args}` chaining blocked \u2014 use `git -C` instead.\n\n"
    "`cd` before `&&` shifts the effective command prefix, breaking\n"
    "allow-rule matching.\n\n"
    "Replace with:\n"
    "    git -C {path} {args}\n\n"
    "This keeps it as a single command without chaining."
)

AND_CHAIN_ADVICE = """\
\u26a0\ufe0f  && chaining detected \u2014 permission friction risk.

The setup command before && shifts the effective command prefix away from
the path-based command that has its own allow rule. The allow rule for the
path-based command won't fire.

Fix this by finding or creating a wrapper:

  1. Existing fish functions:
       ls ~/.config/fish/functions/

  2. Existing git aliases:
       git config --list | grep alias\\.

  3. Existing Claude tools / skill scripts:
       ls ~/.claude/tools/
       find ~/.claude/skills -name '*.sh' | head -20

  4. If no wrapper exists, create ~/.claude/tools/<name>.sh that
     handles both the setup and the command internally, then add:
       Bash(~/.claude/tools/<name>:*)   to settings.local.json allow rules

  5. For independent steps, use separate Bash tool calls instead of &&.

Rewrite the command and resubmit."""

ENV_PREFIX_MSG = (
    "\u26a0\ufe0f  ENV=value prefix before `git` blocked \u2014 permission friction risk.\n\n"
    "The env-var prefix shifts the effective command prefix, breaking\n"
    "allow-rule matching and causing unnecessary permission prompts.\n\n"
    "Solutions:\n"
    "  \u2022 Drop the prefix if unnecessary:\n"
    "      {bare_command}\n"
    "  \u2022 For rebase operations, use aliases:\n"
    "      git develop-rebase    \u2014 interactive rebase onto develop\n"
    "  \u2022 For rebase --continue, no env prefix is needed:\n"
    "      git rebase --continue\n\n"
    "If aliases are missing, run: /Dev10x:git-alias-setup"
)

MERGE_BASE_MSG = (
    "\u26a0\ufe0f  $(git merge-base ...) subshell blocked \u2014 permission friction risk.\n\n"
    "The subshell shifts the effective command prefix, breaking allow-rule\n"
    "matching and causing unnecessary permission prompts.\n\n"
    "Use the git alias instead:\n"
    "    git {alias}\n\n"
    "Available aliases:\n"
    "    git {{branch}}-log       \u2014 log since diverging from branch\n"
    "    git {{branch}}-diff      \u2014 diff since diverging from branch\n"
    "    git {{branch}}-rebase    \u2014 interactive rebase onto branch\n\n"
    "If aliases are missing, run: /Dev10x:git-alias-setup"
)


def _load_all_allow_patterns() -> list[str]:
    patterns: list[str] = []
    for path in SETTINGS_FILES:
        try:
            with open(path) as f:
                data = json.load(f)
            for rule in data.get("permissions", {}).get("allow", []):
                m = re.match(r"^Bash\((.+?)(?::\*)?\)$", rule)
                if m:
                    patterns.append(m.group(1))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    return patterns


def _split_on_and(command: str) -> list[str]:
    return [s.strip() for s in re.split(r"\s*&&\s*", command) if s.strip()]


def _first_token(segment: str) -> str:
    tokens = segment.split()
    return tokens[0] if tokens else ""


def _is_path_based(segment: str) -> bool:
    expanded = os.path.expanduser(segment)
    return any(expanded.startswith(p) or segment.startswith(p) for p in PATH_PREFIXES)


def _matches_allow_rule(
    segment: str,
    patterns: list[str],
) -> str | None:
    expanded_seg = os.path.expanduser(segment)
    for pattern in patterns:
        expanded_pat = os.path.expanduser(pattern)
        if expanded_seg.startswith(expanded_pat) or segment.startswith(pattern):
            return pattern
    return None


def _extract_bare_command(command: str) -> str:
    match = re.match(r"^[A-Z_]+=\S*\s+(.*)", command)
    return match.group(1) if match else command


def _suggest_alias(*, branch: str, subcommand: str | None) -> str:
    if subcommand and branch:
        return f"{branch}-{subcommand}"
    if branch:
        return f"{branch}-log"
    return "{branch}-{action}"


@dataclass
class PrefixFrictionValidator(ValidatorBase):
    name: ClassVar[str] = "prefix-friction"
    rule_id: ClassVar[str] = "DX007"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    capabilities: ClassVar[frozenset[str]] = frozenset({"validate", "correct"})
    _allow_patterns: list[str] | None = field(default=None, repr=False)

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        return (
            "&&" in cmd
            or ENV_PREFIX_GIT_RE.match(cmd) is not None
            or "merge-base" in cmd
            or "git -C" in cmd
            or "rev-parse --show-toplevel" in cmd
        )

    def validate(self, inp: HookInput) -> HookResult | None:
        result = self._check_cd_revparse_chain(command=inp.command)
        if result:
            return result

        result = self._check_git_c_noop(command=inp.command, cwd=inp.cwd)
        if result:
            return result

        result = self._check_env_prefix_git(command=inp.command)
        if result:
            return result

        result = self._check_merge_base(command=inp.command)
        if result:
            return result

        result = self._check_cd_noop_chain(command=inp.command, cwd=inp.cwd)
        if result:
            return result

        result = self._check_cd_git_chain(command=inp.command)
        if result:
            return result

        return self._check_and_chaining(command=inp.command)

    def _check_cd_revparse_chain(
        self,
        *,
        command: str,
    ) -> HookResult | None:
        match = CD_REVPARSE_RE.match(command)
        if not match:
            return None
        bare = match.group(1).strip()
        return HookResult(
            message=CD_REVPARSE_MSG.format(bare_command=bare),
        )

    def _check_git_c_noop(
        self,
        *,
        command: str,
        cwd: str,
    ) -> HookResult | None:
        if not cwd:
            return None
        match = GIT_C_RE.search(command)
        if not match:
            return None
        target = os.path.normpath(os.path.expanduser(match.group(1).strip("\"'")))
        normalized_cwd = os.path.normpath(cwd)
        if target != normalized_cwd:
            return None
        bare = GIT_C_RE.sub("git", command, count=1).strip()
        return HookResult(
            message=GIT_C_NOOP_MSG.format(
                path=match.group(1),
                cwd=cwd,
                bare_command=bare,
            ),
        )

    def _check_cd_noop_chain(
        self,
        *,
        command: str,
        cwd: str,
    ) -> HookResult | None:
        if not cwd:
            return None
        match = CD_NOOP_RE.match(command)
        if not match:
            return None
        target = os.path.normpath(os.path.expanduser(match.group(1).strip("\"'")))
        normalized_cwd = os.path.normpath(cwd)
        if target != normalized_cwd:
            return None
        bare = match.group(2).strip()
        return HookResult(
            message=CD_NOOP_MSG.format(
                path=match.group(1),
                cwd=cwd,
                bare_command=bare,
            ),
        )

    def _check_env_prefix_git(self, *, command: str) -> HookResult | None:
        if ENV_PREFIX_GIT_RE.match(command):
            bare = _extract_bare_command(command=command)
            return HookResult(message=ENV_PREFIX_MSG.format(bare_command=bare))
        return None

    def _check_merge_base(self, *, command: str) -> HookResult | None:
        merge_match = MERGE_BASE_RE.search(command)
        if not merge_match:
            return None
        branch = merge_match.group(1)
        sub_match = GIT_SUBCOMMAND_RE.search(command)
        subcommand = sub_match.group(1) if sub_match else None
        alias = _suggest_alias(branch=branch, subcommand=subcommand)
        return HookResult(message=MERGE_BASE_MSG.format(alias=alias))

    def _check_cd_git_chain(self, *, command: str) -> HookResult | None:
        match = CD_GIT_CHAIN_RE.match(command)
        if not match:
            return None
        path = match.group(1)
        args = match.group(2).strip()
        return HookResult(
            message=CD_GIT_CHAIN_MSG.format(path=path, args=args),
        )

    def _check_and_chaining(self, *, command: str) -> HookResult | None:
        if "&&" not in command:
            return None

        segments = _split_on_and(command)
        if len(segments) < 2:
            return None

        setup_token = _first_token(segments[0])
        if setup_token not in SETUP_TOKENS:
            return None

        if self._allow_patterns is None:
            self._allow_patterns = _load_all_allow_patterns()

        for i, seg in enumerate(segments[1:], start=2):
            if _is_path_based(seg):
                matched = _matches_allow_rule(seg, self._allow_patterns)
                rule_hint = f"Bash({matched}:*)" if matched else "a path-based allow rule"
                detail = (
                    f"segment {i} '{seg[:70]}' would be approved by {rule_hint} "
                    f"but the command starts with '{setup_token}'"
                )
                return HookResult(
                    message=AND_CHAIN_ADVICE + "\nDetected: " + detail,
                )

        return None

    def correct(self, inp: HookInput) -> HookRetry | None:
        from dev10x.domain import HookRetry as _HookRetry

        result = self.validate(inp=inp)
        if result is None:
            return None
        return _HookRetry(message=result.message)
