"""Allow-rule shapes that grant a whole dangerous primitive (GH-1676, GH-1790).

Shared by ``grant`` (triage before a grant is written) and ``spread_guard``
(holding rules back when they are copied between checkouts). Kept apart
from ``grant`` so the spread path can import the tables without the
triage flow: ``grant`` reaches ``merge_worktree_permissions`` through
``generalize``, and the spread guard is imported from there.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dev10x.domain.common.allow_rule import AllowRule
from dev10x.domain.common.bash_tokens import strip_command_wrappers
from dev10x.domain.common.exec_capable import exec_flag, is_interpreter
from dev10x.domain.common.mcp_tool_name import McpToolName, looks_shell_equivalent

# Executables whose allow rule is an arbitrary-code, privilege, egress or
# destruction primitive. `Bash(bash:*)` lets `bash -c "rm -rf /"` past a
# `Bash(rm -rf:*)` deny, because a deny matches only its literal prefix.
UNGRANTABLE_EXECUTABLES = frozenset(
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
UNGRANTABLE_PREFIXES = frozenset(
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
RULE_WILDCARD_SUFFIX_RE = re.compile(r"(?::\*| \*)$")
# Credential and secret stores named by their directory or file, with or
# without a trailing slash or glob. The DX014 operand patterns need an
# exact filename, so `rg x ~/.ssh` and `Read(~/.aws/**)` slipped past them.
# Kept local on purpose: widening DX014 itself would prompt on a plain
# `ls ~/.ssh`, which hook-patterns.md requires to stay silent. Granting a
# rule is the stricter question, so it gets the stricter list.
SENSITIVE_ROOT_RE = re.compile(
    r"(?:(?:^|/|~)\.(?:ssh|aws|azure|gnupg|kube|docker|netrc|pgpass|git-credentials|env"
    r"|npmrc|pypirc|vault-token)"
    r"|\.config/(?:gh|gcloud)|\bid_(?:rsa|dsa|ecdsa|ed25519)|\.pem)(?![\w-])"
)
# The same stores as home-relative paths, so a broad rule that merely
# CONTAINS one (`Read(~/.config/**)` holds `.config/gcloud`) is caught
# even though the rule text never names it.
_SENSITIVE_HOME_PATHS = (
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".kube",
    ".docker",
    ".netrc",
    ".pgpass",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".vault-token",
    ".config/gh",
    ".config/gcloud",
)
_WRITE_TOOLS = frozenset({"Edit", "MultiEdit", "NotebookEdit", "Write"})
_GLOB_CHAR_RE = re.compile(r"[*?\[]")
# The `~/.claude` subtrees the catalog grants writes to on purpose: memory
# and project memory hold no permission decisions. The plugin cache is NOT
# one of them: its hooks and MCP servers run in the next session.
_NARROW_CLAUDE_DIRS = ("memory", "projects")
# Home-relative files and trees whose content runs in a later shell or
# session: rc files, user-level executables, the Dev10x config that
# decides gates and grants.
_EXECUTED_HOME_PATHS = (
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
    ".zshrc",
    ".zshenv",
    ".zprofile",
    ".config/fish",
    ".config/Dev10x",
    ".local/bin",
)
_SYSTEM_WRITE_ROOTS = (Path("/etc"), Path("/usr"))
# Inside a project's own `.claude/`, these entries decide permissions or
# run as hooks; the rest (rules, agents, Dev10x state) does not.
_PROJECT_CLAUDE_CONTROL = re.compile(r"^(?:settings[\w.-]*|hooks)$")


def bash_prefix(*, rule: str) -> str | None:
    """The literal command prefix a ``Bash(...)`` rule allows, or None."""
    parsed = AllowRule.parse(rule)
    if parsed.tool != "Bash":
        return None
    return RULE_WILDCARD_SUFFIX_RE.sub("", parsed.inner).strip()


def blanket_problem(*, rule: str) -> str | None:
    """Why ``rule`` grants a whole code, egress or settings-write primitive, or None.

    Narrower than ``grant.breadth_problem`` on purpose (GH-1790). Copying a
    rule from one checkout to another is a weaker signal than a grant the
    supervisor just triaged, so only the shapes that are dangerous anywhere
    are named here: ``Bash(bash:*)``, ``Bash(python3:*)``, ``Bash(curl:*)``,
    ``Bash(uv run:*)``, ``Edit(~/.claude/**)``. A deep rule such as
    ``Bash(uv run pytest:*)`` stays portable.
    """
    if SENSITIVE_ROOT_RE.search(rule):
        return "The rule names a credential or secret store."
    if McpToolName.is_mcp(rule.strip()):
        return _mcp_problem(rule=rule.strip())
    parsed = AllowRule.parse(rule)
    if parsed.tool in _WRITE_TOOLS:
        return _write_root_problem(pattern=parsed.inner)
    if parsed.tool == "Read":
        return _read_root_problem(pattern=parsed.inner)
    prefix = bash_prefix(rule=rule)
    if prefix is None:
        return None
    return _bash_blanket_problem(prefix=prefix)


def comparable_rule(*, rule: str) -> str:
    """``rule`` in the one spelling two equivalent rules share.

    ``Bash(psql:*)`` and ``Bash(psql *)`` allow the same commands, so a
    declined rule must hold back either spelling (GH-1800).
    """
    stripped = rule.strip()
    prefix = bash_prefix(rule=stripped)
    if prefix is None or not RULE_WILDCARD_SUFFIX_RE.search(AllowRule.parse(stripped).inner):
        return stripped
    return f"Bash({' '.join(prefix.split())}:*)"


def _mcp_problem(*, rule: str) -> str | None:
    """Why an MCP rule hands over a shell, or a whole server, or None.

    A shell-equivalent tool runs commands the Bash validators never see
    (GH-1261), and a server-wide rule grants whatever tool that server adds
    next, shell tools included.
    """
    # Structural split, not McpToolName.parse: server names such as
    # `chrome-devtools` carry characters the strict pattern rejects.
    if "*" in rule or McpToolName.prefix_of(rule) is None:
        return f"`{rule}` grants every tool of an MCP server, including any that run a shell."
    if looks_shell_equivalent(tool=rule.split("__")[-1]):
        return f"`{rule}` runs commands that no Bash guard or deny rule sees."
    return None


def _bash_blanket_problem(*, prefix: str) -> str | None:
    """Why the command prefix grants a whole primitive, or None.

    Env assignments and process wrappers are looked through, so
    ``FOO=1 bash`` and ``timeout 30 sh`` are judged as ``bash`` and ``sh``;
    a wrapper with nothing after it runs whatever follows. An
    ungrantable executable or interpreter followed only by flags
    (``bash -c``, ``python3 -c``, ``rm -rf``) is still the whole tool.
    """
    words = prefix.split()
    if not words or "*" in prefix:
        return "The command prefix is a wildcard."
    run = strip_command_wrappers(parts=words)
    while tuple(run[:2]) in UNGRANTABLE_PREFIXES:
        rest = run[2:]
        if _only_flags(words=rest):
            return f"`{prefix}` can write or run anything."
        # A runner's own options (`uv run --with x python3`) sit between it
        # and the program it runs, so look for that program past them.
        start = next((i for i, word in enumerate(rest) if _whole_tool(word=word)), 0)
        run = rest[start:]
    if not run:
        return f"`{prefix}` is a process wrapper; it runs whatever command follows."
    if _whole_tool(word=run[0]) and _only_flags(words=run[1:]):
        return f"`{prefix}` runs arbitrary code, reaches the network or deletes."
    flag = exec_flag(words=run)
    if flag:
        return f"`{run[0]} {flag}` executes another program."
    return None


def _whole_tool(*, word: str) -> bool:
    return Path(word).name in UNGRANTABLE_EXECUTABLES or is_interpreter(executable=word)


def _only_flags(*, words: list[str]) -> bool:
    return all(word.startswith("-") for word in words)


def _literal_root(*, pattern: str) -> str:
    """``pattern`` cut before the first path segment holding a glob.

    ``~/.claud*/**`` and ``~/**/settings.json`` both reach as far as ``~``,
    so judging only a trailing ``/**`` would miss them.
    """
    segments = pattern.strip().split("/")
    literal = []
    for segment in segments:
        if _GLOB_CHAR_RE.search(segment):
            break
        literal.append(segment)
    return "/".join(literal).rstrip("/") or ("/" if pattern.startswith("/") else "")


def _expanded_root(*, pattern: str) -> Path:
    """The directory or file a path rule is anchored at, normalized."""
    root = _literal_root(pattern=pattern)
    if root.startswith("//"):
        root = root[1:]
    if not root:
        return Path("/")
    home = str(Path.home())
    expanded = root.replace("${HOME}", home, 1).replace("$HOME", home, 1)
    return Path(os.path.normpath(Path(expanded).expanduser()))


def _covers_home(*, path: Path) -> bool:
    """``path`` is home, or an ancestor of it such as ``/`` or ``/home``."""
    return Path.home().is_relative_to(path)


def _write_root_problem(*, pattern: str) -> str | None:
    """Why a write rule over ``pattern`` reaches the user's settings, or None."""
    expanded = _expanded_root(pattern=pattern)
    home = Path.home()
    claude = home / ".claude"
    in_settings_home = expanded.is_relative_to(claude) and not any(
        expanded.is_relative_to(claude / narrow) for narrow in _NARROW_CLAUDE_DIRS
    )
    if (
        _covers_home(path=expanded)
        or in_settings_home
        or expanded == home / ".claude.json"
        or _in_project_claude_control(path=expanded)
    ):
        return (
            f"Writing `{pattern or '*'}` reaches the settings, hooks and memory "
            "that govern every other permission decision."
        )
    executed = [home / relative for relative in _EXECUTED_HOME_PATHS] + list(_SYSTEM_WRITE_ROOTS)
    if any(_overlaps(path=expanded, root=root) for root in executed):
        return (
            f"Writing `{pattern}` reaches a shell rc file, an executable directory "
            "or configuration that later sessions run or obey."
        )
    return None


def _overlaps(*, path: Path, root: Path) -> bool:
    """``path`` lies inside ``root``, or contains it."""
    return path.is_relative_to(root) or root.is_relative_to(path)


def _in_project_claude_control(*, path: Path) -> bool:
    """``path`` is a project ``.claude`` dir itself, its settings or hooks."""
    parts = path.parts
    if ".claude" not in parts:
        return False
    tail = parts[parts.index(".claude") + 1 :]
    return not tail or bool(_PROJECT_CLAUDE_CONTROL.match(tail[0]))


def _read_root_problem(*, pattern: str) -> str | None:
    """Why a read rule over ``pattern`` exposes a credential store, or None."""
    expanded = _expanded_root(pattern=pattern)
    if _covers_home(path=expanded):
        return f"Reading `{pattern or '*'}` reaches ~/.ssh, ~/.aws and every other secret."
    home = Path.home()
    if any((home / store).is_relative_to(expanded) for store in _SENSITIVE_HOME_PATHS):
        return f"Reading `{pattern}` reaches a credential or secret store."
    return None


__all__ = [
    "RULE_WILDCARD_SUFFIX_RE",
    "SENSITIVE_ROOT_RE",
    "UNGRANTABLE_EXECUTABLES",
    "UNGRANTABLE_PREFIXES",
    "bash_prefix",
    "blanket_problem",
    "comparable_rule",
]
