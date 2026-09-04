"""Validator: redirect raw CLI commands to their skill/tool equivalents.

Loads validation rules from command-skill-map.yaml at module level.
Only processes rules where matcher=Bash and hook_block=true.

Supports three friction levels:

  strict   — hard deny (exit 2), no fallback shown
  guided   — hard deny + fallback instructions in systemMessage (default)
  adaptive — allow + warning in additionalContext (future)

The YAML is the single source of truth shared with
Dev10x:diag-friction (formerly Dev10x:skill-reinforcement). User
overrides:
  ~/.config/Dev10x/diag-friction.yaml
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.common.bash_tokens import split_tokens
from dev10x.domain.common.branch_name import PROTECTED_BRANCHES
from dev10x.domain.documents.config_document import Config
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.rules.validation_rule import Compensation
from dev10x.validators.base import ValidatorBase

if TYPE_CHECKING:
    from dev10x.domain import HookRetry
    from dev10x.domain.rules.rule_engine import RuleEngine


# ── GH-963: safe direct push detection ──────────────────────────
#
# An unattended agent with no human channel and no MCP server can
# get permanently stuck: `push_safe` is unreachable, the wrapper
# script is blocked with "use the MCP tool", and raw `git push` is
# blocked with "use Skill(Dev10x:git)" — each block names the other
# as the remedy. This narrows the `git-push` deny (Option 1 from the
# issue) so the ordinary, safe case — a non-force push that names an
# explicit, non-protected branch — never needs MCP or the skill at
# all. Anything else (bare push with no resolvable target, a
# symbolic `HEAD` ref, or any bare `--force`/`-f`) still requires the
# skill/MCP path, matching push_safe's own guardrail.
_BARE_FORCE_TOKENS = frozenset({"--force", "-f"})

# GH-1047: a single-dash, no-`=` token is a bundle of short flags, so
# `-uf` carries a force push that whole-token membership never sees.
_SHORT_FLAG_CLUSTER_RE = re.compile(r"^-[A-Za-z]+$")

# Flags whose value is a SEPARATE token (GH-1049 gap 2). Filtering only
# `-`-prefixed tokens left the value behind as a positional, shifting
# every index after it — `git push -o ci.skip origin main` resolved its
# target to `origin`, so `main` never reached the protected-branch check.
#
# Optional-value flags are deliberately absent: `--force-with-lease` is
# commonly spelled bare, and consuming the token after it would swallow
# the remote. Attached `--flag=value` spellings are single tokens and
# need no entry here.
_VALUE_TAKING_FLAGS = frozenset(
    {
        "-o",
        "--push-option",
        "--receive-pack",
        "--exec",
        "--repo",
    }
)

# Shell constructs whose value is unknown until execution (GH-1049 gap 6).
# A substitution can produce a force flag or a protected target with no
# matching token in the parsed text, so what this guard cannot read, it
# must not clear.
_EXPANSION_RE = re.compile(r"\$\(|\$\{|\$[A-Za-z_]|`")

# A ref may arrive fully qualified (GH-1049 gap 4). `PROTECTED_BRANCHES`
# holds short names, so `refs/heads/main` compared as unprotected.
_REF_PREFIX = "refs/heads/"


def _tokenize(command: str) -> list[str]:
    return split_tokens(command=command)


def _push_args(command: str) -> list[str] | None:
    """Tokens following the ``git push`` subcommand, or ``None``.

    The subcommand is located as the first ``push`` token that has a
    ``git`` token somewhere before it, rather than the first bare
    ``push`` anywhere in the string (GH-1049 gap 5) — otherwise a decoy
    in `echo push && git push …` shifted every positional offset.
    """
    tokens = _tokenize(command)
    for index, token in enumerate(tokens):
        if token == "push" and "git" in tokens[:index]:
            return tokens[index + 1 :]
    return None


def _push_positionals(push_args: list[str]) -> list[str]:
    """The remote and refspecs, with flag values excluded (gap 2)."""
    positionals: list[str] = []
    skip_value = False
    for arg in push_args:
        if skip_value:
            skip_value = False
            continue
        if arg.startswith("-"):
            skip_value = arg in _VALUE_TAKING_FLAGS
            continue
        positionals.append(arg)
    return positionals


def _normalize_ref(refspec: str) -> str:
    """The short branch name a refspec targets.

    Takes the destination half of `src:dst`, drops a leading `+` (the
    force marker on a colon-less refspec), and unqualifies
    `refs/heads/<x>` so it compares against `PROTECTED_BRANCHES`.
    """
    ref = refspec.split(":")[-1].removeprefix("+")
    return ref.removeprefix(_REF_PREFIX)


def _explicit_push_targets(command: str) -> list[str] | None:
    """Every branch this push names explicitly, if statically determinable.

    Returns ``None`` when no target can be resolved without inspecting
    live git state — bare ``git push``, ``git push origin`` (no
    refspec), or a symbolic ``HEAD`` ref — so callers stay conservative
    rather than guessing the current branch.

    ALL refspecs are returned, not just the first (GH-1049 gap 3): a
    push may carry several, and inspecting one let
    `git push origin feature +evil:develop` read as safe.
    """
    push_args = _push_args(command)
    if push_args is None:
        return None
    positionals = _push_positionals(push_args)
    if len(positionals) < 2:
        return None
    targets = [_normalize_ref(refspec) for refspec in positionals[1:]]
    return None if "HEAD" in targets else targets


def _has_bare_force(command: str) -> bool:
    """True when ``command`` carries a bare force flag.

    Long options are matched exactly so ``--force-with-lease`` — which
    is deliberately allowed — never matches on a substring. Short-flag
    clusters are decomposed letter-by-letter instead, because POSIX
    bundling lets a force push be spelled without a lone ``-f`` token.
    """
    return any(
        token in _BARE_FORCE_TOKENS
        or (_SHORT_FLAG_CLUSTER_RE.match(token) is not None and "f" in token)
        for token in _tokenize(command)
    )


def _has_refspec_force(command: str) -> bool:
    """True when a refspec force-pushes via its ``+`` prefix (gap 3).

    `git push origin +evil:main` carries no force *flag* at all, so a
    flag-only test reported it as an ordinary push.
    """
    push_args = _push_args(command)
    if push_args is None:
        return False
    return any(refspec.startswith("+") for refspec in _push_positionals(push_args)[1:])


def _has_force(command: str) -> bool:
    return _has_bare_force(command) or _has_refspec_force(command)


def _is_safe_direct_push(command: str) -> bool:
    """True when ``command`` is safe to allow without MCP/skill involvement.

    Safe means: no force in any spelling, and explicit,
    statically-resolvable target branches, none of which is in
    ``PROTECTED_BRANCHES``. This is exactly the guardrail
    ``push_safe``/``git-push-safe.sh`` already enforce for the
    force+protected combination — narrowing the deny here doesn't
    weaken it, it just stops blocking the case those tools would
    have allowed anyway.

    A command carrying shell expansion is never safe (gap 6): its real
    arguments are decided after this check runs, so the only sound
    verdict is to fail closed onto the skill/MCP rail.
    """
    if _EXPANSION_RE.search(command):
        return False
    if _has_force(command):
        return False
    targets = _explicit_push_targets(command)
    if not targets:
        return False
    return all(target not in PROTECTED_BRANCHES for target in targets)


def _format_correction_msg(
    *,
    label: str,
    comp: Compensation,
) -> str:
    if comp.type == "use-tool":
        return (
            f"Permission denied for `{label}`. Use the MCP tool instead:\n\n"
            f"  Tool: `{comp.tool}`\n\n"
            f"The raw CLI command was denied because it bypasses structured\n"
            f"responses and causes permission friction ({comp.guardrails})."
        )
    return (
        f"Permission denied for `{label}`. Use the skill instead:\n\n"
        f"  Skill: `Skill({comp.skill})`\n\n"
        f"The raw CLI command was denied because it bypasses guardrails\n"
        f"that the skill enforces ({comp.guardrails})."
    )


_YAML_PATH = Path(__file__).parent / "command-skill-map.yaml"

SKIP_ENV_VAR = "DEV10X_SKIP_CMD_VALIDATION"

# Boolean (un-rationalized) form: =true / =1 / =yes — REJECTED (GH-226).
# Skill authors must now provide a rationale string instead.
BOOLEAN_SKIP_RE = re.compile(
    rf"^{SKIP_ENV_VAR}=(true|1|yes)\s+",
    re.IGNORECASE,
)

# Rationale form: a quoted non-empty string of at least 20 chars.
# This is the only form that legitimately bypasses validation.
RATIONALE_SKIP_RE = re.compile(
    rf'^{SKIP_ENV_VAR}="([^"]{{20,}})"\s+',
)

UNRATIONALIZED_SKIP_MSG = f"""\
⛔  Un-rationalized {SKIP_ENV_VAR} bypass — rejected.

The boolean form ({SKIP_ENV_VAR}=true / =1 / =yes) is no longer
accepted. It was being used as a procedural escape hatch instead
of as a deliberate, skill-authorized exception.

Before reaching for this flag, the agent MUST exhaust the
alternatives the hook is steering toward:

  1. Invoke the skill named in the block message (the skill exists
     precisely to enforce the guardrails the raw command bypasses).
  2. Use the MCP tool wrapper if the block names one — MCP calls
     avoid the permission friction that drives this flag.
  3. If a temp-file path or pathspec is the issue, use the mktmp
     MCP tool / `git add` exclusion pathspec — never silent bypass.
  4. If the MCP server is unavailable, reconnect via `/mcp` or a
     session restart — do NOT skip validation as a workaround.

ONLY when the above are genuinely depleted and you are authoring
or executing inside a skill that legitimately needs the raw
command, prefix it with a rationale string of at least 20 chars
explaining why:

  {SKIP_ENV_VAR}="<reason: what skill, what alternative failed>" <command>

The rationale is recorded by the hook so the escape hatch stays
auditable. Boolean forms are NOT a shortcut for "I already tried"."""

OVERRIDE_HINT = (
    f"\n\n⚠️  Do NOT use {SKIP_ENV_VAR} as a shortcut "
    "to silence this block. That flag is reserved for SKILL AUTHORS "
    "whose skill legitimately needs the raw command — it is NOT an "
    "escape hatch for agents reacting to a hook message.\n\n"
    "If you reached this hint because a command was blocked, the "
    "correct response is to invoke the skill named above. Reaching "
    "for the skip flag because the task “looks simple”, "
    "because you already prepared inputs, or out of inertia is a "
    "procedural error — the skill exists precisely to enforce the "
    "guardrails you would otherwise skip.\n\n"
    "ONLY if you are authoring or executing inside such a skill — "
    "and you have exhausted skill / MCP-tool / mktmp alternatives — "
    "prefix it with a rationale string of at least 20 chars:\n"
    f'  {SKIP_ENV_VAR}="<reason for bypass>" <command>\n\n'
    f"The boolean form ({SKIP_ENV_VAR}=true) is rejected (GH-226)."
)

MCP_UNAVAILABLE_HINT = (
    "\n\n\u26a0\ufe0f  If the MCP server is disconnected "
    '(tool listed as "no longer available" in system-reminders), '
    "ask the user to reconnect via `/mcp` or a session "
    f"restart. Do NOT use {SKIP_ENV_VAR} as a workaround — that "
    "flag is reserved for skill-authorized exceptions, not transient "
    "MCP unavailability.\n\n"
    "While you wait, READ-ONLY `gh api` calls are NOT blocked and are "
    "the sanctioned fallback for gathering state (GH-1173 F2):\n"
    "  gh api repos/<owner>/<repo>/pulls/<n>\n"
    "  gh api repos/<owner>/<repo>/issues/<n>\n"
    "  gh api graphql -f query='...'   # e.g. reviewThreads state\n"
    "Only state-CHANGING operations must wait for the wrapper — a "
    "write is what these guardrails exist to gate. An unattended "
    "agent told only to stop, with no named alternative, either "
    "stalls on a prompt nobody will answer or reaches for the skip "
    "flag; neither is the intended behaviour."
)


_CONFIG: Config | None = None
_ENGINE: RuleEngine | None = None


def _load_config(yaml_path: Path = _YAML_PATH) -> tuple[Config, RuleEngine]:
    from dev10x.config.loader import load_config
    from dev10x.domain.rules.rule_engine import RuleEngine

    full = load_config(yaml_path=yaml_path)
    engine = RuleEngine.from_config(config=full)
    config = Config(
        plugin_repo=full.plugin_repo,
        rules=engine.command_rules,
    )
    return config, engine


def _get_config_and_engine() -> tuple[Config, RuleEngine]:
    global _CONFIG, _ENGINE
    if _CONFIG is None or _ENGINE is None:
        _CONFIG, _ENGINE = _load_config()
    return _CONFIG, _ENGINE


# "npm" gates the node-tests-npm-monorepo block (GH-880): without it,
# should_run() short-circuits before evaluate_command() ever sees an
# `npm --prefix <dir> test` shape. "psql" does the same for psql-write
# (GH-1034) — of that rule's verbs only CREATE happened to contain an
# existing token, so DROP/DELETE/UPDATE/… never reached the engine.
# The fast-path filter is intentionally broad — evaluate_command() still
# applies the precise per-rule regex.
_QUICK_TOKENS = frozenset(
    [
        "commit",
        "create",
        "push",
        "rebase",
        "checks",
        "issue",
        "merge",
        "edit",
        "api",
        "npm",
        "psql",
    ]
)

_COMMIT_HEAL_MSG = (
    "\u26d4  `git commit` blocked — wrong temp file path.\n\n"
    "The `-F` path must be under `/tmp/Dev10x/git/`.\n"
    "Create it with: `mcp__plugin_Dev10x_cli__mktmp("
    'namespace="git", prefix="commit-msg", ext=".txt")`\n'
    "then: `git commit -F <returned-path>`\n\n"
    "If you used a different namespace (e.g. `commit` instead of "
    "`git`), that is why this was blocked."
)

_WRONG_TEMP_PATH_RE = re.compile(r"-F\s+/tmp/Dev10x/(?!git/)\S+/\S+\.\S+")


def _format_skill_msg(
    *,
    label: str,
    comp: Compensation,
    plugin_repo: str,
) -> str:
    """Render the block message for a redirected command.

    The fallback clause used to be conditional on the ADR-0002
    ``friction_level`` axis, which only ever shipped as ``guided``.
    GH-1194 collapsed the axis, so the clause is unconditional — an
    agent that cannot reach the sanctioned path always sees what to do
    instead.
    """
    file_issue_hint = (
        f"\n\nIf you are inside a skill that instructed this command, "
        f"file an issue at {plugin_repo} — the skill needs updating."
        if plugin_repo
        else ""
    )
    if comp.type == "use-tool":
        mcp_fallback = (
            f"If the MCP server is unavailable, fall back to:\n{comp.description}"
            if comp.description
            else ""
        )
        sep = "\n\n" if mcp_fallback else ""
        return (
            f"\u26d4  `{label}` blocked — use the MCP tool instead.\n\n"
            f"  Tool: `{comp.tool}`\n\n"
            f"Why: Raw CLI bypasses structured responses and causes\n"
            f"permission friction ({comp.guardrails})."
            f"{sep}{mcp_fallback}"
            f"{MCP_UNAVAILABLE_HINT}"
            f"{file_issue_hint}{OVERRIDE_HINT}"
        )

    skill_fallback = (
        f"If the skill fails, apply these guardrails manually:\n{comp.fallback}"
        if comp.fallback
        else ""
    )
    sep = "\n\n" if skill_fallback else ""
    return (
        f"\u26d4  `{label}` blocked — use the skill instead.\n\n"
        f"  Skill: `Skill({comp.skill})`\n\n"
        f"Why: Raw CLI bypasses guardrails that the skill enforces\n"
        f"({comp.guardrails})."
        f"{sep}{skill_fallback}"
        f"{file_issue_hint}{OVERRIDE_HINT}"
    )


@dataclass
class SkillRedirectValidator(ValidatorBase):
    name: ClassVar[str] = "skill-redirect"
    rule_id: ClassVar[str] = "DX006"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD

    def should_run(self, inp: HookInput) -> bool:
        # Rationale form is the only valid bypass — skip the validator
        # entirely so the wrapped command runs without further checks.
        if RATIONALE_SKIP_RE.match(inp.command):
            return False
        # Boolean form must still run so validate() can reject it; the
        # order matters because a malformed rationale could otherwise
        # also match the boolean pattern.
        if BOOLEAN_SKIP_RE.match(inp.command):
            return True
        cmd_lower = inp.command.lower()
        return any(token in cmd_lower for token in _QUICK_TOKENS)

    def validate(self, inp: HookInput) -> HookResult | None:
        if BOOLEAN_SKIP_RE.match(inp.command):
            return HookResult(message=UNRATIONALIZED_SKIP_MSG)
        config, engine = _get_config_and_engine()
        rule = engine.evaluate_command(command=inp.command)
        if rule is None:
            return None
        if rule.name == "git-push" and _is_safe_direct_push(inp.command):
            return None
        comp = rule.compensations[0] if rule.compensations else None
        if not comp:
            return None
        if comp.skill == "Dev10x:git-commit" and _WRONG_TEMP_PATH_RE.search(inp.command):
            return HookResult(message=_COMMIT_HEAL_MSG)
        label = rule.compiled_patterns[0].pattern
        msg = _format_skill_msg(
            label=label,
            comp=comp,
            plugin_repo=config.plugin_repo,
        )
        return HookResult(message=msg)

    def correct(self, inp: HookInput) -> HookRetry | None:
        from dev10x.domain import HookRetry as _HookRetry

        _, engine = _get_config_and_engine()
        rule = engine.evaluate_command(command=inp.command)
        if rule is None:
            return None
        comp = rule.compensations[0] if rule.compensations else None
        if not comp:
            return None
        label = rule.compiled_patterns[0].pattern
        msg = _format_correction_msg(label=label, comp=comp)
        return _HookRetry(message=msg)
