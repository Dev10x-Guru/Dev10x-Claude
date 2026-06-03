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
  ~/.claude/memory/Dev10x/diag-friction.yaml
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from dev10x.domain import HookInput, HookResult
from dev10x.domain.documents.config_document import Config
from dev10x.domain.friction_level import FrictionLevel
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.rules.validation_rule import Compensation
from dev10x.validators.base import ValidatorBase

if TYPE_CHECKING:
    from dev10x.domain import HookRetry
    from dev10x.domain.rules.rule_engine import RuleEngine


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
    "STOP and ask the user to reconnect via `/mcp` or a session "
    f"restart. Do NOT use {SKIP_ENV_VAR} as a workaround — that "
    "flag is reserved for skill-authorized exceptions, not transient "
    "MCP unavailability."
)


_CONFIG: Config | None = None
_ENGINE: RuleEngine | None = None


def _load_config(yaml_path: Path = _YAML_PATH) -> tuple[Config, RuleEngine]:
    from dev10x.config.loader import load_config
    from dev10x.domain.rules.rule_engine import RuleEngine

    full = load_config(yaml_path=yaml_path)
    engine = RuleEngine.from_config(config=full)
    config = Config(
        friction_level=full.friction_level,
        plugin_repo=full.plugin_repo,
        rules=engine.command_rules,
    )
    return config, engine


def _get_config_and_engine() -> tuple[Config, RuleEngine]:
    global _CONFIG, _ENGINE
    if _CONFIG is None or _ENGINE is None:
        _CONFIG, _ENGINE = _load_config()
    return _CONFIG, _ENGINE


_QUICK_TOKENS = frozenset(
    ["commit", "create", "push", "rebase", "checks", "issue", "merge", "edit", "api"]
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
    friction_level: FrictionLevel,
    plugin_repo: str,
) -> str:
    file_issue_hint = (
        f"\n\nIf you are inside a skill that instructed this command, "
        f"file an issue at {plugin_repo} — the skill needs updating."
        if plugin_repo
        else ""
    )
    if comp.type == "use-tool":
        mcp_fallback = friction_level.fallback_guidance(
            fallback=(
                f"If the MCP server is unavailable, fall back to:\n{comp.description}"
                if comp.description
                else ""
            )
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

    skill_fallback = friction_level.fallback_guidance(
        fallback=(
            f"If the skill fails, apply these guardrails manually:\n{comp.fallback}"
            if comp.fallback
            else ""
        )
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
    capabilities: ClassVar[frozenset[str]] = frozenset({"validate", "correct"})

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
        comp = rule.compensations[0] if rule.compensations else None
        if not comp:
            return None
        if comp.skill == "Dev10x:git-commit" and _WRONG_TEMP_PATH_RE.search(inp.command):
            return HookResult(message=_COMMIT_HEAL_MSG)
        label = rule.compiled_patterns[0].pattern
        msg = _format_skill_msg(
            label=label,
            comp=comp,
            friction_level=config.friction_level,
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
