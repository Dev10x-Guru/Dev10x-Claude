"""Strategy: shell-equivalent-mcp-tools (GH-1261).

An MCP tool that runs a shell command or evaluates arbitrary code is a
Bash call that does not look like one. The PreToolUse chain exits on
``tool_name != "Bash"`` before any validator runs, so DX001-DX016 never
see it; every ``Bash()`` deny in settings stops applying to the same
effect; and the skill-redirect hook routes nothing.

That makes a single such tool worth more than a suggestion: it does not
weaken one guardrail, it makes the whole Bash layer optional. The
finding names which denies stop being enforceable, because "this tool
can run shell commands" understates what the reader needs to decide.

This is GH-1260's sharpest case — rules match a tool name and a command
string, never an effect — so detection is by name here too, and is
therefore a floor rather than a guarantee. A server exposing the same
capability under a name nobody listed goes unseen; the catalogued deny
is what actually stops the known ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dev10x.skills.doctor.strategy import Context, Finding, Remediation, Strategy
from dev10x.skills.permission.enumerate_mcp import discover_all_mcp_servers

# Word sequences that mark a tool as running a shell or evaluating code,
# matched against the tool name's own `_`-separated words. Deliberately
# short and generic: a new server naming its shell tool `run_command` or
# `eval_python` should trip this without an edit here.
#
# Matching words rather than substrings is what keeps `eval` usable as a
# marker. As a substring it also fires on `get_evaluation_report`, and a
# critical finding against a harmless read is worse than a miss — it
# teaches the reader to skim past this strategy.
_SHELL_MARKERS = (
    ("execute", "terminal"),
    ("execute", "command"),
    ("run", "command"),
    ("shell",),
    ("execute", "code"),
    ("eval",),
    ("evaluate",),
    ("execute", "tool"),
)

# What stops being enforceable. Named rather than described, because the
# point is the size of the hole, not the existence of one.
_VOIDED = (
    "DX001-DX016 (the whole PreToolUse validator chain)",
    "every Bash() deny — sudo, git push --force, rm -rf, "
    "gh api --method DELETE, git config --global",
    "the skill-redirect hook (gh pr edit -> update_pr, and the rest)",
)


def _looks_shell_equivalent(tool: str) -> bool:
    words = tuple(tool.lower().split("_"))
    return any(
        marker == words[start : start + len(marker)]
        for marker in _SHELL_MARKERS
        for start in range(len(words))
    )


@dataclass(frozen=True)
class ShellEquivalentRemediation:
    """Remediation payload for a shell-equivalent-mcp-tools finding."""

    tool: str
    prefix: str

    def to_remediation(self, *, finding: Finding) -> Remediation:
        return Remediation(
            kind="edit_settings",
            target="permissions.deny",
            action={
                "rule": self.tool,
                "prefix": self.prefix,
                "reason": (
                    "Runs a shell command or arbitrary code without being a "
                    "Bash call, so it bypasses " + "; ".join(_VOIDED) + "."
                ),
            },
        )


def _settings_paths_from_context(context: Context) -> list[Path]:
    paths = list(context.settings_paths)
    if not paths:
        home = Path.home()
        paths = [
            home / ".claude" / "settings.json",
            home / ".claude" / "settings.local.json",
        ]
    return paths


def detect(context: Context) -> list[Finding]:
    """Flag every allowed MCP tool that can run a shell or evaluate code."""
    findings: list[Finding] = []
    for server in discover_all_mcp_servers(settings_paths=_settings_paths_from_context(context)):
        for tool in sorted(server.tools):
            if not _looks_shell_equivalent(tool):
                continue
            findings.append(
                Finding(
                    strategy_id="shell-equivalent-mcp-tools",
                    severity="critical",
                    location="permissions.allow",
                    evidence=(
                        f"``{tool}`` runs a shell command or arbitrary code "
                        f"without being a Bash call, so it bypasses: " + "; ".join(_VOIDED)
                    ),
                    proposed_fix=(
                        f"Move ``{tool}`` to permissions.deny. A hook or deny "
                        'that keys on tool_name == "Bash" does not constrain '
                        "an MCP tool that shells out, so allowing it makes "
                        "every Bash-layer guardrail optional."
                    ),
                    data=ShellEquivalentRemediation(tool=tool, prefix=server.prefix),
                )
            )
    return findings


def remediate(finding: Finding) -> Remediation:
    """Propose denying the tool."""
    return finding.to_remediation()


STRATEGY = Strategy(
    id="shell-equivalent-mcp-tools",
    description=(
        "Flag MCP tools that run a shell command or evaluate arbitrary "
        "code. Such a tool is a Bash call the PreToolUse chain never "
        "sees, so it voids DX001-DX016 and every Bash() deny at once."
    ),
    detect=detect,
    remediate=remediate,
)
