"""Validator: command prefix friction patterns.

Consolidates detect-and-chaining.py and block-alias-covered-commands.py.

Blocks patterns that shift the effective command prefix, breaking
allow-rule matching:
  1. && chaining with setup commands (mkdir, cd, export, etc.)
  2. ENV=value git ... prefix
  3. $(git merge-base ...) subshells
  4. git -c <key>=<value> config-override prefix (GH-488 S19 / #35/#38/#40)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from dev10x.domain import HookAllow, HookInput, HookResult
from dev10x.domain.claude_paths import ClaudeDir
from dev10x.domain.common.allow_rule import AllowRule, AllowRuleLoader
from dev10x.domain.common.bash_tokens import GIT_C_DIR_RE
from dev10x.domain.profile_tier import ProfileTier
from dev10x.validators.base import ValidatorBase

if TYPE_CHECKING:
    from collections.abc import Callable

    from dev10x.domain import HookRetry

SETUP_TOKENS = frozenset(
    ["mkdir", "cd", "export", "source", ".", "pushd", "popd", "touch", "unset"]
)

PATH_PREFIXES = (
    f"{ClaudeDir.skills_dir()}/",
    f"{ClaudeDir.tools_dir()}/",
    f"{ClaudeDir.hooks_dir()}/",
    "~/.claude/skills/",
    "~/.claude/tools/",
    "~/.claude/hooks/",
)

SETTINGS_FILES = [
    str(ClaudeDir.settings_local_json()),
    str(ClaudeDir.settings_json()),
]

# Lowercase `-c <key>=<value>` config override *before* the subcommand —
# distinct from `git -C <dir>` above. This is the GH-488 prefix-shift family
# (evidence #35/#38/#40): `git -c core.pager=cat <verb>` was a pervasive agent
# habit (4 hits in one session), and `git -c core.hooksPath=/dev/null` is the
# dangerous arm (disables hooks). The `-c <kv>` prefix shifts the matched
# command string so `Bash(git <verb>:*)` never fires and only the over-broad
# `git *` is offered as "don't ask again".
GIT_C_CONFIG_RE = re.compile(r"\bgit\s+-c\s+(?P<key>[\w.]+)=(?P<value>\S+)")
ENV_PREFIX_GIT_RE = re.compile(r"^[A-Z_]+=\S*\s+git\b")
MERGE_BASE_RE = re.compile(r"\$\(git\s+merge-base\s+(\w+)\s+HEAD\)")
GIT_SUBCOMMAND_RE = re.compile(r"\bgit\s+(log|diff|rebase)\b")

CD_NOOP_RE = re.compile(r'^cd\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)\s*&&\s*(.*)')
CD_REVPARSE_RE = re.compile(r'^cd\s+"?\$\(git\s+rev-parse\s+--show-toplevel\)"?\s*&&\s*(.*)')
CD_GIT_CHAIN_RE = re.compile(r'^cd\s+("(?:[^"]+)"|\'(?:[^\']+)\'|\S+)\s*&&\s*git\b\s*(.*)')

# GH-485: `uv run [ENV-FLAGS] <inner>` places environment-only flags
# between `uv run` and the tool, shifting the matched prefix so existing
# allow rules (`Bash(uv run pytest:*)`, `Bash(python manage.py:*)`) never
# fire — every monorepo tool would otherwise need its own
# `uv run --directory * <tool>` rule (whack-a-mole), pushing users toward
# the `uv run *` fence-tool footgun. We strip the env-only prefix and
# re-match the inner command; the inner command's own tier governs, so
# auto-approval can never widen what the inner command isn't already
# allowed to do.
#
# `--with <pkg>` installs an arbitrary dependency into the ephemeral
# env — a supply-chain surface, unlike the pure-environment flags. It is
# therefore NOT stripped: its presence DISQUALIFIES the command from
# auto-approval, so `uv run --with <pkg> <tool>` falls through to the
# normal `uv run` fence-tool ask rather than being silently approved
# (GH-485 `--with` caveat; aligns with the fence-tool ask policy).
# `uv run [--extra dev] pre-commit …` / `uvx pre-commit …` — pre-commit is on
# PATH, so the `uv run` wrapper (and any `--extra` env flag) only shifts the
# matched prefix away from `Bash(pre-commit:*)` and forces an approval prompt.
# Route to the bare `pre-commit` invocation (GH-717 follow-up).
_UV_PRECOMMIT_RE = re.compile(r"^\s*(?:uvx|uv\s+run\b)[^|&;]*?\s+pre-commit\b(?P<rest>[^|&;]*)")

_UV_RUN_RE = re.compile(r"^\s*uv\s+run\b(?P<rest>.*)$", re.DOTALL)
_UV_ENV_VALUE_FLAGS = frozenset({"--directory", "--project", "--python", "--extra"})
_UV_ENV_BOOL_FLAGS = frozenset({"--frozen", "--no-project", "--locked", "--no-sync"})


def _strip_uv_run_env_flags(command: str) -> str | None:
    """Return the inner command after stripping ``uv run`` + env-only flags.

    Returns ``None`` when the command is not a ``uv run`` invocation, when
    no env-only flag was present (plain ``uv run <tool>`` already matches
    its allow rule natively), or when ``--with <pkg>`` is present — an
    arbitrary-package install must not be auto-approved (see above), so its
    presence disqualifies the command and leaves the fence-tool ask intact.

    This doubles as the ``should_run`` gate: a non-``None`` return is
    exactly the set of commands the uv-run normalization check acts on, so
    the flag list lives here in one place.
    """
    match = _UV_RUN_RE.match(command)
    if not match:
        return None
    tokens = match.group("rest").split()
    idx = 0
    stripped_any = False
    while idx < len(tokens):
        token = tokens[idx]
        if token == "--with" or token.startswith("--with="):
            return None
        if token in _UV_ENV_VALUE_FLAGS:
            idx += 2
        elif token in _UV_ENV_BOOL_FLAGS or any(
            token.startswith(f"{flag}=") for flag in _UV_ENV_VALUE_FLAGS
        ):
            idx += 1
        else:
            break
        stripped_any = True
    if not stripped_any:
        return None
    inner = " ".join(tokens[idx:]).strip()
    return inner or None


# GH-119: redirect followed by positional args swallows the post-redirect
# tokens in Claude Code's command-shape classifier, breaking allow-rule
# matching. Match commands shaped like `<cmd> ... 2>/dev/null -name X`
# where the redirect appears before any trailing positional/option arg.
REDIRECT_THEN_POSITIONAL_RE = re.compile(
    r"^(?P<cmd>find|grep|ls|rg)\s+"
    r"(?P<before>[^|;]*?)"
    r"(?P<redirect>\d?>(?:&\d|/\S+))\s+"
    r"(?P<after>-\S+|[^|&;<>]\S*)"
)

# GH-119: ';' chains match the whole command string against allow rules
# rather than individual clauses. Detect non-trivial chains (two
# read-only or low-risk commands) so the agent splits them into separate
# tool calls. Excludes `; ` inside quoted strings via a lookbehind
# heuristic — the initial filter is by token shape on the chain head/tail.
#
# GH-127 #5: head/tail set widened to catch the documented nuisance
# patterns (e.g., `git status; git fetch`, `ls dir1; ls dir2`,
# `pwd; whoami`). Each entry is a command that does not, in its most
# common forms, mutate global state beyond the working directory —
# chains of these are nearly always two probes that should be split
# into two Bash tool calls. State-changing commands (rm, mv, cp,
# mkdir, touch, kubectl apply, docker run, etc.) are intentionally
# absent: forcing a split there would be more disruptive than helpful.
_CHAIN_HEAD_RE = (
    r"(?:find|grep|ls|rg|cat|head|tail|wc|"
    r"git|gh|pwd|which|whoami|env|date|printenv|"
    r"echo|sleep|uv|python|python3|docker|kubectl)"
)
SEMICOLON_CHAIN_RE = re.compile(
    rf"^\s*(?P<head>{_CHAIN_HEAD_RE}\b[^;]*?)"
    r"\s*;\s*"
    rf"(?P<tail>{_CHAIN_HEAD_RE}\b.*)$"
)

# GH-258: shell loops wrap allowed commands and shift the effective
# command prefix to the loop keyword (`for`, `while`, `until`).
# `Bash(gh api:*)` does not match `for n in 1 2 3; do gh api ... ; done`
# because the matcher sees `for` as the leading token. Same regression
# family as `cd ... &&` chaining (DX007 existing rules) and `for/xargs`
# wrappers documented in CLAUDE.md and `.claude/rules/hook-patterns.md`.
# The proposed remedy is the parallel-Bash-tool-call pattern.
_LOOP_KEYWORDS = ("for", "while", "until")
SHELL_LOOP_HEAD_RE = re.compile(
    r"^\s*(?P<keyword>for|while|until)\b[^;]*?;\s*do\b\s*(?P<body>.+?)(?:;\s*done\b.*)?$",
    re.DOTALL,
)
XARGS_WRAP_RE = re.compile(r"\|\s*xargs\b(?P<rest>[^|;]*)")
FIND_EXEC_WRAP_RE = re.compile(r"\bfind\b[^|;]*?-exec\s+(?P<rest>[^;]+?)(?:\\;|';'|\+)")
_WRAPPED_INNER_TOKENS = frozenset(
    {"gh", "git", "kubectl", "docker", "psql", "aws", "uv", "python", "python3"}
)
# GH-726 F2/F3: `find … -exec <search-tool>` is the archetypal un-allowable
# search shape — `find -exec` can't be auto-allowed and the inner search
# tool's own allow rule never fires inside `-exec`. Unlike the mutating
# inners above (where the remedy is parallel Bash calls), the correct steer
# for a *search* is ripgrep / the Grep tool, which recurse and filter by
# glob in one pre-approved call. Listed separately so the find branch can
# emit a search-specific message instead of the parallel-calls advice.
_FIND_SEARCH_INNER_TOKENS = frozenset(
    {"grep", "egrep", "fgrep", "rg", "cat", "head", "tail", "wc", "sort", "sed", "awk"}
)

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

GIT_C_PAGER_MSG = (
    "⚠️  `git -c core.pager=cat` blocked — redundant and breaks "
    "allow-rule matching.\n\n"
    "git does not page when stdout is not a TTY, which is always the case for\n"
    "tool calls — so `-c core.pager=cat` is pure noise. Worse, a `-c <kv>`\n"
    "override *before* the subcommand shifts the matched command string, so\n"
    '`Bash(git <verb>:*)` never fires and the only "don\'t ask again" option\n'
    "offered is the over-broad `git *`.\n\n"
    "Drop the prefix and run the verb directly:\n"
    "    {bare_command}\n\n"
    "If you want an explicit non-paging form, use the sanctioned alias:\n"
    "    git nopager <verb> …      (pre-approved via Bash(git nopager:*))\n"
    "Missing it? Run: /Dev10x:git-alias-setup"
)

GIT_C_COLOR_MSG = (
    "⚠️  `git -c color.ui=never` blocked — redundant and breaks "
    "allow-rule matching.\n\n"
    "git omits color when stdout is not a TTY, which is always the case for\n"
    "tool calls — so `-c color.ui=never` is pure noise. Worse, a `-c <kv>`\n"
    "override *before* the subcommand shifts the matched command string, so\n"
    '`Bash(git <verb>:*)` never fires and the only "don\'t ask again" option\n'
    "offered is the over-broad `git *`.\n\n"
    "Drop the prefix and run the verb directly:\n"
    "    {bare_command}\n\n"
    "If color genuinely leaks (e.g. `color.ui=always` in config), use the\n"
    "sanctioned alias:\n"
    "    git nocolor <verb> …      (pre-approved via Bash(git nocolor:*))\n"
    "Missing it? Run: /Dev10x:git-alias-setup"
)

GIT_C_HOOKSPATH_MSG = (
    "\U0001f6ab  `git -c core.hooksPath={value}` blocked — disables git hooks "
    "(safety).\n\n"
    "`-c core.hooksPath=…` turns off the repo's git hooks AND, as a `-c <kv>`\n"
    "prefix, shifts the matched command string so allow-rule matching breaks.\n"
    "On a mutating verb this is a security downgrade — never widen it to `git *`.\n\n"
    "Run the verb without the prefix:\n"
    "    {bare_command}\n\n"
    "If a hook is genuinely misfiring, fix the hook — don't disable it."
)

GIT_C_CONFIG_MSG = (
    "⚠️  `git -c {key}={value}` prefix blocked — breaks allow-rule "
    "matching.\n\n"
    "A `-c <kv>` config override before the subcommand shifts the matched\n"
    "command string, so `Bash(git <verb>:*)` never fires — the only\n"
    '"don\'t ask again" option offered is the over-broad `git *`.\n\n'
    "If the override is unnecessary, drop it:\n"
    "    {bare_command}\n\n"
    "If you need it repeatedly, provision a stable, pre-approvable alias:\n"
    "    /Dev10x:git-alias-setup    (e.g. `git <name>` → Bash(git <name>:*))"
)

GIT_C_EDITOR_MSG = (
    "⚠️  `git -c {key}=…` (editor override) blocked — and unnecessary.\n\n"
    "The `-c <kv>` prefix shifts the matched command string so\n"
    "`Bash(git rebase:*)` never fires. You don't need it to rebase\n"
    "unattended:\n\n"
    "  • After a content conflict, plain `git rebase --continue` reuses the\n"
    "    commit message verbatim — no editor opens in a non-TTY tool call.\n"
    "  • For interactive / autosquash rebases, use the pre-approved aliases\n"
    "    (they bake in `GIT_SEQUENCE_EDITOR=true`) or the grooming skill:\n"
    "        git autosquash-develop      (or -main / -master / -trunk)\n"
    "        Dev10x:git-groom            (non-interactive history cleanup)\n\n"
    "Drop the prefix and run:\n"
    "    {bare_command}\n\n"
    "Missing the aliases? Run: /Dev10x:git-alias-setup"
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

REDIRECT_THEN_POSITIONAL_MSG = (
    "⚠️  Redirect before positional args blocked — permission friction risk.\n\n"
    "`{cmd} ... {redirect} {after}` swallows post-redirect tokens in\n"
    "Claude Code's command-shape classifier. The allow rule for `{cmd}`\n"
    "never gets a chance to fire because the classifier bails out\n"
    "with 'Redirect has multiple targets'.\n\n"
    "Move the redirect to the end of the command:\n"
    "    {cmd} {before} {after} {redirect}\n"
)

SEMICOLON_CHAIN_MSG = (
    "⚠️  `;` chain blocked — permission friction risk.\n\n"
    "Claude Code matches the whole command string against allow rules,\n"
    "not individual clauses. So `Bash({head_cmd}:*)` does NOT cover\n"
    "`{head_cmd} ... ; {tail_cmd} ...` even when both halves are\n"
    "individually allowed.\n\n"
    "Split into separate Bash tool calls instead.\n"
)

SHELL_LOOP_WRAP_MSG = (
    "⚠️  Shell {wrapper} wraps an allowed command (`{inner}`) — permission friction risk.\n\n"
    "Claude Code's allow-rule matcher keys on the leading token of the\n"
    "command string. For `{wrapper}`, that token is `{wrapper}` — not\n"
    "`{inner}`. So `Bash({inner}:*)` does NOT cover this call.\n\n"
    "Use parallel Bash tool calls instead — one per iteration.\n"
    "Tool calls in a single message run concurrently, which is faster\n"
    "than a serial shell loop and each iteration matches its own\n"
    "allow rule cleanly.\n\n"
    "Example: send N separate Bash calls in one message, each running\n"
    "`{inner} ...` with the iteration value substituted in.\n"
)

FIND_EXEC_SEARCH_MSG = (
    "⚠️  `find … -exec {inner} …` blocked — and the wrong tool for the job.\n\n"
    "`find -exec` can't be auto-allowed (it runs an arbitrary command), and\n"
    "`{inner}`'s own allow-rule never fires inside `-exec`. For *searching*\n"
    "files, reach for ripgrep or the Grep tool instead — both recurse and\n"
    "filter by glob in a single pre-approved call:\n\n"
    "  • `rg <pattern> -g '<glob>' <path>`  — ripgrep recurses by default\n"
    "    (no `-type f`); `-g` does the name globs; `-l` lists matching files\n"
    "    (== `grep -l`). `Bash(rg:*)` is already a shipped allow-rule.\n"
    "  • The built-in Grep tool — wraps ripgrep, needs no Bash allow-rule\n"
    '    at all (use output_mode="files_with_matches" / "count").\n\n'
    "One `rg`/Grep call replaces the whole find → filter → search pipeline.\n"
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


UV_RUN_NORMALIZE_MSG = (
    "✓ `uv run` env-flags stripped — inner command `{inner}` matches an "
    "existing Bash allow-rule (Dev10x DX007)."
)

UV_PRECOMMIT_MSG = (
    "⚠️  `uv run … pre-commit` blocked — run pre-commit directly.\n\n"
    "pre-commit is installed on PATH, so the `uv run` wrapper (and any\n"
    "`--extra dev`) only shifts the matched command string — "
    "`Bash(pre-commit:*)`\n"
    "never fires and you get an approval prompt every time.\n\n"
    "Run it directly:\n"
    "    {bare_command}\n\n"
    "If pre-commit is missing, install it once:\n"
    "    pipx install pre-commit       (preferred — isolated)\n"
    "    pip install --user pre-commit"
)


def _load_all_allow_patterns() -> list[str]:
    patterns: list[str] = []
    for path in SETTINGS_FILES:
        for rule in AllowRuleLoader.load(path):
            m = re.match(r"^Bash\((.+?)(?::\*)?\)$", rule)
            if m:
                patterns.append(m.group(1))
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
    signature = f"Bash({segment})"
    for pattern in patterns:
        if AllowRule.bash(f"{pattern}:*").matches(signature):
            return pattern
    return None


def _extract_bare_command(command: str) -> str:
    match = re.match(r"^[A-Z_]+=\S*\s+(.*)", command)
    return match.group(1) if match else command


def _strip_git_c_config(command: str) -> str:
    """Drop every ``-c <key>=<value>`` token and collapse the gap.

    ``git -c core.pager=cat status --porcelain`` → ``git status --porcelain``;
    multiple ``-c`` flags are all removed.
    """
    bare = re.sub(r"\s+-c\s+[\w.]+=\S+", "", command)
    return re.sub(r"\s{2,}", " ", bare).strip()


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
    _allow_patterns: list[str] | None = field(default=None, repr=False)

    def _checks(self) -> list[Callable[..., HookResult | HookAllow | None]]:
        """Return the ordered chain of bound prefix-check callables.

        ``validate`` walks this list in order; the last entry is the
        fall-through ``&&``-chaining check. Adding a check only requires
        adding an entry here — no separate name-string to keep in sync.
        """
        return [
            self._check_uv_run_precommit,
            self._check_uv_run_inner_allow,
            self._check_cd_revparse_chain,
            self._check_git_c_noop,
            self._check_git_c_config,
            self._check_env_prefix_git,
            self._check_merge_base,
            self._check_cd_noop_chain,
            self._check_cd_git_chain,
            self._check_redirect_then_positional,
            self._check_semicolon_chain,
            self._check_shell_loop_wrap,
            self._check_and_chaining,
        ]

    def should_run(self, inp: HookInput) -> bool:
        cmd = inp.command
        return (
            "&&" in cmd
            or ENV_PREFIX_GIT_RE.match(cmd) is not None
            or "merge-base" in cmd
            or "git -C" in cmd
            or GIT_C_CONFIG_RE.search(cmd) is not None
            or "rev-parse --show-toplevel" in cmd
            # GH-119: shapes that bypass allow-rule prefix matching
            or ";" in cmd
            or re.search(r"\d?>(?:&\d|/\S+)", cmd) is not None
            # GH-258: shell loops/xargs/find -exec wrap allowed commands
            or any(re.search(rf"\b{kw}\b", cmd) for kw in _LOOP_KEYWORDS)
            or "xargs" in cmd
            or "-exec" in cmd
            # GH-485: `uv run [env-flags] <inner>` prefix normalization —
            # the strip helper is the single source of truth for the flag set.
            or _strip_uv_run_env_flags(cmd) is not None
            # GH-717 follow-up: `uv run … pre-commit` / `uvx pre-commit`
            or ("pre-commit" in cmd and ("uv run" in cmd or "uvx" in cmd))
        )

    def validate(self, inp: HookInput) -> HookResult | HookAllow | None:
        for check in self._checks():
            result: HookResult | HookAllow | None = check(inp=inp)
            if result is not None:
                return result
        return None

    def _check_uv_run_precommit(self, *, inp: HookInput) -> HookResult | None:
        match = _UV_PRECOMMIT_RE.match(inp.command)
        if not match:
            return None
        rest = match.group("rest")
        bare = f"pre-commit{rest}".rstrip()
        return HookResult(message=UV_PRECOMMIT_MSG.format(bare_command=bare))

    def _check_uv_run_inner_allow(self, *, inp: HookInput) -> HookAllow | None:
        inner = _strip_uv_run_env_flags(inp.command)
        if inner is None:
            return None
        if self._allow_patterns is None:
            self._allow_patterns = _load_all_allow_patterns()
        if not self._allow_patterns:
            return None
        # Match both the bare inner command (`python manage.py …` →
        # `Bash(python manage.py:*)`) and the env-flag-stripped normalized
        # form (`uv run pytest …` → `Bash(uv run pytest:*)`). Either hit
        # means the inner command is independently allowed.
        normalized = f"uv run {inner}"
        if (
            _matches_allow_rule(inner, self._allow_patterns) is not None
            or _matches_allow_rule(normalized, self._allow_patterns) is not None
        ):
            return HookAllow(message=UV_RUN_NORMALIZE_MSG.format(inner=inner))
        return None

    def _check_cd_revparse_chain(self, *, inp: HookInput) -> HookResult | None:
        match = CD_REVPARSE_RE.match(inp.command)
        if not match:
            return None
        bare = match.group(1).strip()
        return HookResult(
            message=CD_REVPARSE_MSG.format(bare_command=bare),
        )

    def _check_git_c_noop(self, *, inp: HookInput) -> HookResult | None:
        if not inp.cwd:
            return None
        match = GIT_C_DIR_RE.search(inp.command)
        if not match:
            return None
        target = os.path.normpath(os.path.expanduser(match.group(1).strip("\"'")))
        normalized_cwd = os.path.normpath(inp.cwd)
        if target != normalized_cwd:
            return None
        bare = GIT_C_DIR_RE.sub("git", inp.command, count=1).strip()
        return HookResult(
            message=GIT_C_NOOP_MSG.format(
                path=match.group(1),
                cwd=inp.cwd,
                bare_command=bare,
            ),
        )

    def _check_git_c_config(self, *, inp: HookInput) -> HookResult | None:
        match = GIT_C_CONFIG_RE.search(inp.command)
        if not match:
            return None
        key = match.group("key")
        value = match.group("value")
        bare = _strip_git_c_config(inp.command)
        if key == "core.hooksPath":
            return HookResult(
                message=GIT_C_HOOKSPATH_MSG.format(value=value, bare_command=bare),
            )
        if key == "core.pager":
            return HookResult(message=GIT_C_PAGER_MSG.format(bare_command=bare))
        if key == "color.ui":
            return HookResult(message=GIT_C_COLOR_MSG.format(bare_command=bare))
        if key in ("core.editor", "sequence.editor"):
            return HookResult(
                message=GIT_C_EDITOR_MSG.format(key=key, bare_command=bare),
            )
        return HookResult(
            message=GIT_C_CONFIG_MSG.format(key=key, value=value, bare_command=bare),
        )

    def _check_cd_noop_chain(self, *, inp: HookInput) -> HookResult | None:
        if not inp.cwd:
            return None
        match = CD_NOOP_RE.match(inp.command)
        if not match:
            return None
        target = os.path.normpath(os.path.expanduser(match.group(1).strip("\"'")))
        normalized_cwd = os.path.normpath(inp.cwd)
        if target != normalized_cwd:
            return None
        bare = match.group(2).strip()
        return HookResult(
            message=CD_NOOP_MSG.format(
                path=match.group(1),
                cwd=inp.cwd,
                bare_command=bare,
            ),
        )

    def _check_env_prefix_git(self, *, inp: HookInput) -> HookResult | None:
        if ENV_PREFIX_GIT_RE.match(inp.command):
            bare = _extract_bare_command(command=inp.command)
            return HookResult(message=ENV_PREFIX_MSG.format(bare_command=bare))
        return None

    def _check_merge_base(self, *, inp: HookInput) -> HookResult | None:
        merge_match = MERGE_BASE_RE.search(inp.command)
        if not merge_match:
            return None
        branch = merge_match.group(1)
        sub_match = GIT_SUBCOMMAND_RE.search(inp.command)
        subcommand = sub_match.group(1) if sub_match else None
        alias = _suggest_alias(branch=branch, subcommand=subcommand)
        return HookResult(message=MERGE_BASE_MSG.format(alias=alias))

    def _check_cd_git_chain(self, *, inp: HookInput) -> HookResult | None:
        match = CD_GIT_CHAIN_RE.match(inp.command)
        if not match:
            return None
        path = match.group(1)
        args = match.group(2).strip()
        return HookResult(
            message=CD_GIT_CHAIN_MSG.format(path=path, args=args),
        )

    def _check_redirect_then_positional(self, *, inp: HookInput) -> HookResult | None:
        match = REDIRECT_THEN_POSITIONAL_RE.match(inp.command)
        if not match:
            return None
        cmd = match.group("cmd")
        before = match.group("before").strip()
        redirect = match.group("redirect")
        after = match.group("after")
        return HookResult(
            message=REDIRECT_THEN_POSITIONAL_MSG.format(
                cmd=cmd,
                before=before,
                redirect=redirect,
                after=after,
            )
        )

    def _check_semicolon_chain(self, *, inp: HookInput) -> HookResult | None:
        match = SEMICOLON_CHAIN_RE.match(inp.command)
        if not match:
            return None
        head_cmd = match.group("head").strip().split()[0]
        tail_cmd = match.group("tail").strip().split()[0]
        return HookResult(
            message=SEMICOLON_CHAIN_MSG.format(
                head_cmd=head_cmd,
                tail_cmd=tail_cmd,
            )
        )

    def _check_shell_loop_wrap(self, *, inp: HookInput) -> HookResult | None:
        command = inp.command
        loop_match = SHELL_LOOP_HEAD_RE.match(command)
        if loop_match:
            inner = self._inner_command_from(body=loop_match.group("body"))
            if inner:
                return HookResult(
                    message=SHELL_LOOP_WRAP_MSG.format(
                        wrapper=loop_match.group("keyword"),
                        inner=inner,
                    ),
                )

        xargs_match = XARGS_WRAP_RE.search(command)
        if xargs_match:
            inner = self._first_non_flag_token(text=xargs_match.group("rest"))
            if inner in _WRAPPED_INNER_TOKENS:
                return HookResult(
                    message=SHELL_LOOP_WRAP_MSG.format(wrapper="xargs", inner=inner),
                )

        find_match = FIND_EXEC_WRAP_RE.search(command)
        if find_match:
            inner = self._first_non_flag_token(text=find_match.group("rest"))
            if inner in _WRAPPED_INNER_TOKENS:
                return HookResult(
                    message=SHELL_LOOP_WRAP_MSG.format(wrapper="find -exec", inner=inner),
                )
            if inner in _FIND_SEARCH_INNER_TOKENS:
                return HookResult(
                    message=FIND_EXEC_SEARCH_MSG.format(inner=inner),
                )

        return None

    def _first_non_flag_token(self, *, text: str) -> str | None:
        # Skip leading option flags and their values. Recognized
        # value-taking short flags for `xargs` and `find -exec`.
        value_flags = {"-I", "-n", "-P", "-J", "-L", "-E", "-d", "-s", "-name"}
        tokens = text.strip().split()
        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            if token in value_flags:
                idx += 2
                continue
            if token.startswith("-"):
                idx += 1
                continue
            return token
        return None

    def _inner_command_from(self, *, body: str) -> str | None:
        for clause in re.split(r"\s*(?:;|&&|\|\|)\s*", body):
            tokens = clause.strip().split()
            if not tokens:
                continue
            head = tokens[0]
            if head in _WRAPPED_INNER_TOKENS:
                return head
        return None

    def _check_and_chaining(self, *, inp: HookInput) -> HookResult | None:
        command = inp.command
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
        if result is None or isinstance(result, HookAllow):
            return None
        return _HookRetry(message=result.message)
